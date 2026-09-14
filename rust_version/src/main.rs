use tokio;
use serde_json;
use clap;
use async_openai::{self, Client};
use async_openai::config::OpenAIConfig;
use async_openai::error::OpenAIError;
use async_openai::types::chat::{
    ChatCompletionMessageToolCalls, ChatCompletionRequestAssistantMessageArgs,
    ChatCompletionRequestMessage, ChatCompletionRequestSystemMessageArgs,
    ChatCompletionRequestToolMessageArgs, ChatCompletionRequestUserMessageArgs,
    CreateChatCompletionRequestArgs, ReasoningEffort,
};
use clap::{Arg, Command};
use rewrite_hackson::all_tools::get_tools;
use rewrite_hackson::functions::{dispatch_tool, find_tests_dir, load_requirements, normalize, to_markdown};
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};


const  SYSTEM_PROMPT :&str= r#"你是一个编程 agent,任务是实现一个 web 项目，让 Playwright E2E 测试通过。

需求: {requirements}
测试: {tests}
项目: {output}

项目模板已就位: frontend/ 是 Vite + React 19 + TS + Tailwind 4,入口 frontend/src/pages/HomePage.tsx;backend/ 是 Express 5 + SQLite,单端口托管 frontend/dist。
测试依赖的初始数据要写进 backend/src/database/seed_db.js(现在是空壳)，再用 npm run db:prepare:e2e 准备 E2E 数据库。

分批读需求,逐步实现。需求里的文本、按钮名、label、placeholder 必须完全一致。完成后运行前端构建确认通过。"#;

const MAX_STEPS:usize=120;
const REQUEST_TIMEOUT:u64=300;
const MAX_RETRIES:usize=2;
const RETRY_DELAY:u64=2;

pub async fn react_loop(
    client:&Client<OpenAIConfig>,
    model:&str,
    system_prompt:&str,
    output_dir:&Path,
)->Result<(),String>{
    let mut messages:Vec<ChatCompletionRequestMessage>=vec![
        ChatCompletionRequestSystemMessageArgs::default()
            .content(system_prompt)
            .build()
            .map_err(|e|e.to_string())?
            .into(),
        ChatCompletionRequestUserMessageArgs::default()
            .content("开始实现。")
            .build()
            .map_err(|e|e.to_string())?
            .into(),
    ];

    for step in 0..MAX_STEPS{
        eprintln!("[step {}/{}] requesting {model}...",step+1,MAX_STEPS);
        let request=CreateChatCompletionRequestArgs::default()
            .model(model)
            .messages(messages.clone())
            .tools(get_tools())
            .reasoning_effort(ReasoningEffort::Low)
            .build()
            .map_err(|e|e.to_string())?;

        let started=Instant::now();
        let mut attempt=0;
        let response=loop{
            match tokio::time::timeout(
                Duration::from_secs(REQUEST_TIMEOUT),
                client.chat().create(request.clone()),
            ).await{
                Ok(Ok(response))=>break response,
                Ok(Err(error))=>{
                    if attempt>=MAX_RETRIES||!retryable(&error){
                        return Err(format!("request failed: {error}"));
                    }
                    attempt+=1;
                    eprintln!("  request failed ({error}), retry {attempt}/{MAX_RETRIES}...");
                    tokio::time::sleep(Duration::from_secs(RETRY_DELAY)).await;
                }
                Err(_)=>{
                    if attempt>=MAX_RETRIES{
                        return Err(format!("request timed out after {REQUEST_TIMEOUT}s"));
                    }
                    attempt+=1;
                    eprintln!("  request timed out after {REQUEST_TIMEOUT}s, retry {attempt}/{MAX_RETRIES}...");
                }
            }
        };
        let message=response.choices.into_iter().next()
            .ok_or_else(||"no choices in response".to_string())?
            .message;

        let mut assistant=ChatCompletionRequestAssistantMessageArgs::default();
        if let Some(content)=message.content.clone(){
            assistant.content(content);
        }
        if let Some(tool_calls)=message.tool_calls.clone(){
            assistant.tool_calls(tool_calls);
        }
        messages.push(assistant.build().map_err(|e|e.to_string())?.into());

        let Some(tool_calls)=message.tool_calls else{
            eprintln!("[step {}/{}] no tool calls, finished in {:.1}s",step+1,MAX_STEPS,started.elapsed().as_secs_f64());
            return Ok(());
        };
        eprintln!("[step {}/{}] {} tool call(s) in {:.1}s",step+1,MAX_STEPS,tool_calls.len(),started.elapsed().as_secs_f64());

        for call in tool_calls{
            let ChatCompletionMessageToolCalls::Function(call)=call else{
                continue;
            };
            let arguments=if call.function.arguments.trim().is_empty(){
                "{}"
            }else{
                call.function.arguments.as_str()
            };
            let result=match serde_json::from_str::<Value>(arguments){
                Ok(args)=>dispatch_tool(&call.function.name,&args,output_dir),
                Err(_)=>format!("error: invalid JSON arguments: {}",call.function.arguments),
            };
            eprintln!("  {}({}) -> {}",call.function.name,arguments,preview(&result));
            messages.push(
                ChatCompletionRequestToolMessageArgs::default()
                    .content(result)
                    .tool_call_id(call.id)
                    .build()
                    .map_err(|e|e.to_string())?
                    .into(),
            );
        }
    }

    Err(format!("react loop exceeded {MAX_STEPS} steps"))
}



fn retryable(error:&OpenAIError)->bool{
    match error{
        OpenAIError::Reqwest(_)=>true,
        OpenAIError::ApiError(response)=>{
            response.status_code.as_u16()==429||response.status_code.is_server_error()
        }
        _=>false,
    }
}

fn preview(text:&str)->String{
    let first=text.lines().next().unwrap_or("");
    let mut out:String=first.chars().take(160).collect();
    if out.chars().count()<first.chars().count()||text.lines().count()>1{
        out.push_str(" ...");
    }
    out
}

pub struct Args{
    pub requirement_path:String,
    pub output_dir:String,
    pub task_type:String,
}

pub fn parse_args()->Args{
    let matches=Command::new("agent")
        .about("Run the ARC-Bench agent.")
        .arg(Arg::new("requirement_path").index(1).required(false))
        .arg(Arg::new("output_dir").long("output-dir"))
        .arg(Arg::new("task_type").long("type"))
        .get_matches();

    Args{
        requirement_path:matches.get_one::<String>("requirement_path").cloned()
            .unwrap_or_else(||env_or("ARCBENCH_TASK_DIR","requirements")),
        output_dir:matches.get_one::<String>("output_dir").cloned()
            .unwrap_or_else(||env_or("ARCBENCH_OUTPUT_DIR",".")),
        task_type:matches.get_one::<String>("task_type").cloned()
            .unwrap_or_else(||env_or("ARCBENCH_TASK_TYPE","web")),
    }
}

fn env_or(key:&str,fallback:&str)->String{
    std::env::var(key).unwrap_or_else(|_|fallback.to_string())
}

fn absolute(path:&Path)->PathBuf{
    let joined=if path.is_absolute(){
        path.to_path_buf()
    }else{
        std::env::current_dir().unwrap_or_default().join(path)
    };
    normalize(&joined)
}

pub fn copy_template(template_dir:&Path,output_dir:&Path)->Result<(),String>{
    if !template_dir.is_dir(){
        return Err(format!("Template directory not found: {}",template_dir.display()));
    }
    fs::create_dir_all(output_dir).map_err(|e|e.to_string())?;

    let mut sources:Vec<PathBuf>=fs::read_dir(template_dir).map_err(|e|e.to_string())?
        .flatten()
        .map(|entry|entry.path())
        .collect();
    sources.sort();

    for source in sources{
        let destination=output_dir.join(source.file_name().unwrap_or_default());
        if source.is_dir(){
            copy_dir_all(&source,&destination).map_err(|e|e.to_string())?;
        }else if source.is_file(){
            if let Some(parent)=destination.parent(){
                fs::create_dir_all(parent).map_err(|e|e.to_string())?;
            }
            fs::copy(&source,&destination).map_err(|e|e.to_string())?;
        }
    }
    Ok(())
}

fn copy_dir_all(source:&Path,destination:&Path)->std::io::Result<()>{
    fs::create_dir_all(destination)?;
    for entry in fs::read_dir(source)?{
        let entry=entry?;
        let target=destination.join(entry.file_name());
        if entry.path().is_dir(){
            copy_dir_all(&entry.path(),&target)?;
        }else{
            fs::copy(entry.path(),&target)?;
        }
    }
    Ok(())
}

pub async fn run_agent(requirements_dir:&Path,output_dir:&Path)->Result<(),String>{
    let template_dir=Path::new(env!("CARGO_MANIFEST_DIR")).join("template");
    copy_template(&template_dir,output_dir)?;

    let requirements=match load_requirements(requirements_dir){
        Ok(requirements)=>requirements,
        Err(error)=>{
            eprintln!("requirements parse failed, skipping traceability: {error}");
            Vec::new()
        }
    };

    let api_key=std::env::var("OPENAI_API_KEY").unwrap_or_default().trim().to_string();
    if api_key.is_empty(){
        return Err("OPENAI_API_KEY is required".to_string());
    }
    let base_url=std::env::var("OPENAI_BASE_URL").unwrap_or_default().trim().to_string();
    let mut config=OpenAIConfig::new().with_api_key(&api_key);
    if !base_url.is_empty(){
        config=config.with_api_base(&base_url);
    }
    let client=Client::with_config(config);

    let model=std::env::var("MODEL").or_else(|_|std::env::var("OPENAI_MODEL"))
        .unwrap_or_default().trim().to_string();
    let model=if model.is_empty(){"deepseek-v4-flash".to_string()}else{model};

    let mut requirements_ref=requirements_dir.to_string_lossy().into_owned();
    if !requirements.is_empty(){
        let digest=output_dir.join(".arc").join("requirements.md");
        if let Some(parent)=digest.parent(){
            fs::create_dir_all(parent).map_err(|e|e.to_string())?;
        }
        fs::write(&digest,to_markdown(&requirements)).map_err(|e|e.to_string())?;
        requirements_ref=digest.to_string_lossy().into_owned();
    }

    let tests=find_tests_dir(output_dir);
    let tests=if tests.is_empty(){"评测时注入 backend/test-e2e/，当前不可见".to_string()}else{tests};
    let output_ref=output_dir.to_string_lossy().into_owned();
    let system_prompt=SYSTEM_PROMPT
        .replace("{requirements}",&requirements_ref)
        .replace("{tests}",&tests)
        .replace("{output}",&output_ref);

    react_loop(&client,&model,&system_prompt,output_dir).await
}

#[tokio::main]
async fn main() {
    let _=dotenv::from_path(Path::new(env!("CARGO_MANIFEST_DIR")).join(".env"));
    let args=parse_args();
    let requirements_dir=absolute(Path::new(&args.requirement_path));
    let output_dir=absolute(Path::new(&args.output_dir));
    if let Err(error)=run_agent(&requirements_dir,&output_dir).await{
        eprintln!("{error}");
        std::process::exit(1);
    }
}
