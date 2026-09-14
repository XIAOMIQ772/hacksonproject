use std::process::{Command, Stdio};
use std::path::{Path, PathBuf};
use std::path::Component;
use std::collections::HashSet;
use std::fs;
use serde_json::{Map, Value};
const MAX_OUTPUT_CHARS:usize=16000;

pub fn clip(text:&str)->String{
    if text.len()<MAX_OUTPUT_CHARS{
        text.to_string()
    }
    else{
        let end=text.floor_char_boundary(MAX_OUTPUT_CHARS);
        format!("{}\n<output clipped>",&text[..end])
    }
}

pub fn run_bash(command:&str,cwd:&str)->String{
    let out=Command::new("bash").arg("-c").arg(command).current_dir(cwd).stdin(Stdio::null()).output();
    match out{
        Ok(output)=>{
            let mut str=String::from_utf8_lossy(&output.stdout).into_owned();
            str.push_str(&String::from_utf8_lossy(&output.stderr));
            let clipped=clip(&str);
            if clipped.is_empty(){"(no output)".to_string()}else{clipped}
        }
        Err(_)=>"something wrong".to_string()
    }
}

pub fn resolve(raw_path:&str,root:&Path)->PathBuf{
    let path = Path::new(raw_path);
    let joined = if path.is_absolute() {
        path.to_path_buf()
    } 
    else {
        root.join(raw_path)
    };
    joined.canonicalize().unwrap_or(joined)
}

pub fn run_read(args:&Value,root:&Path)->String{
    let path=resolve(&arg_str(args,"path"),root);

    if path.is_dir(){
        let mut entries=collect_entries(&path);
        entries.sort();
        let listed=clip(&entries.join("\n"));
        return if listed.is_empty(){"(empty directory)".to_string()}else{listed};
    }
    if !path.is_file(){
        return format!("error: {} does not exist",path.display());
    }

    let bytes=match fs::read(&path){Ok(b)=>b,Err(e)=>return format!("error: {e}")};
    let text=String::from_utf8_lossy(&bytes);
    let lines:Vec<&str>=text.lines().collect();

    let start=args.get("offset").and_then(Value::as_i64).unwrap_or(1).max(1) as usize;
    let from=(start-1).min(lines.len());
    let mut selected=&lines[from..];
    if let Some(limit)=args.get("limit").and_then(Value::as_i64){
        let limit=limit.max(0) as usize;
        selected=&selected[..selected.len().min(limit)];
    }

    let body=selected.iter().enumerate()
        .map(|(i,line)|format!("{:6}\t{}",start+i,line))
        .collect::<Vec<_>>().join("\n");
    clip(&body)
}

pub fn run_write(args:&Value,root:&Path)->String{
    let content=match args.get("content"){
        None|Some(Value::Null)=>return "error: content is required".to_string(),
        Some(v)=>python_str(v),
    };
    let path=normalize(&resolve(&arg_str(args,"path"),root));
    if !path.starts_with(root){
        return format!("error: path must be inside {}",root.display());
    }
    if let Some(parent)=path.parent(){
        if let Err(e)=fs::create_dir_all(parent){
            return format!("error: {e}");
        }
    }
    match fs::write(&path,content){
        Ok(_)=>format!("wrote {}",path.display()),
        Err(e)=>format!("error: {e}"),
    }
}

pub fn run_edit(args:&Value,root:&Path)->String{
    let old=match args.get("old"){
        None|Some(Value::Null)=>return "error: old is required".to_string(),
        Some(v)=>python_str(v),
    };
    let path=normalize(&resolve(&arg_str(args,"path"),root));
    if !path.starts_with(root){
        return format!("error: path must be inside {}",root.display());
    }
    if !path.is_file(){
        return format!("error: {} does not exist",path.display());
    }

    let content=match fs::read_to_string(&path){Ok(c)=>c,Err(e)=>return format!("error: {e}")};
    let count=content.matches(&old).count();
    if count==0{
        return "error: old not found in file".to_string();
    }
    if count>1{
        return format!("error: old appears {count} times; make it unique");
    }
    let new=arg_str(args,"new");
    match fs::write(&path,content.replace(&old,&new)){
        Ok(_)=>format!("edited {}",path.display()),
        Err(e)=>format!("error: {e}"),
    }
}

pub fn dispatch_tool(name:&str,args:&Value,root:&Path)->String{
    match name{
        "bash"=>run_bash(&arg_str(args,"command"),root.to_str().unwrap_or("")),
        "read"=>run_read(args,root),
        "write"=>run_write(args,root),
        "edit"=>run_edit(args,root),
        other=>format!("error: unknown tool {other}"),
    }
}

pub fn find_tests_dir(output_dir:&Path)->String{
    let candidate=output_dir.join("backend").join("test-e2e");
    if candidate.is_dir(){candidate.to_string_lossy().into_owned()}else{String::new()}
}

pub fn read_requirements_data(requirements_dir:&Path)->Result<Value,String>{
    let yaml_path=requirements_dir.join("requirements.yaml");
    if yaml_path.is_file(){
        let text=fs::read_to_string(&yaml_path).map_err(|e|e.to_string())?;
        return serde_yaml::from_str(&text).map_err(|e|e.to_string());
    }

    let json_path=requirements_dir.join("requirement.txt");
    if json_path.is_file(){
        let text=fs::read_to_string(&json_path).map_err(|e|e.to_string())?;
        let payload:Value=serde_json::from_str(&text).map_err(|e|e.to_string())?;
        if let Value::Object(map)=&payload{
            if let Some(Value::String(embedded))=map.get("requirements_yaml"){
                if !embedded.is_empty(){
                    return serde_yaml::from_str(embedded).map_err(|e|e.to_string());
                }
            }
        }
        return Ok(payload);
    }

    Err(format!("no requirements.yaml or requirement.txt in {}",requirements_dir.display()))
}

#[derive(Debug,Clone)]
pub struct Requirement{
    pub id:String,
    pub name:String,
    pub description:String,
    pub scenarios:Option<Vec<Value>>,
    pub parent_id:Option<String>,
    pub children_ids:Vec<String>,
    pub dependencies:Vec<Value>,
}

pub fn load_requirements(requirements_dir:&Path)->Result<Vec<Requirement>,String>{
    let data=read_requirements_data(requirements_dir)?;
    let mut out=Vec::new();
    let mut seen=HashSet::new();
    visit(&data,None,"",&mut out,&mut seen);
    if out.is_empty(){
        return Err("no recognizable requirement nodes".to_string());
    }
    Ok(out)
}

pub fn to_markdown(requirements:&[Requirement])->String{
    let mut parts:Vec<String>=Vec::new();
    for req in requirements{
        let depth=(req.id.matches('.').count()+2).min(6);
        parts.push(format!("\n{} {} {}\n","#".repeat(depth),req.id,req.name));
        parts.push(req.description.clone());

        for scenario in req.scenarios.iter().flatten(){
            let Some(sc)=scenario.as_object() else{
                parts.push(format!("\n- {}",python_str(scenario)));
                continue;
            };
            let name=truthy_field(sc,"name").map(python_str).unwrap_or_else(||"Scenario".to_string());
            parts.push(format!("\n- {name}"));

            let steps=sc.get("steps").and_then(|v|if is_truthy(v){v.as_array()}else{None});
            if let Some(steps)=steps{
                for step in steps{
                    match step.as_object(){
                        Some(so)=>{
                            let keyword=so.get("keyword").map(python_str).unwrap_or_else(||"None".to_string());
                            let content=so.get("content").map(python_str).unwrap_or_else(||"None".to_string());
                            parts.push(format!("  - {keyword}: {content}"));
                        }
                        None=>parts.push(format!("  - {}",python_str(step))),
                    }
                }
            }
        }
    }
    parts.join("\n")
}

fn visit(value:&Value,parent_id:Option<&str>,key_hint:&str,out:&mut Vec<Requirement>,seen:&mut HashSet<String>){
    match value{
        Value::Array(items)=>{
            for item in items{
                visit(item,parent_id,"",out,seen);
            }
            return;
        }
        Value::Object(_)=>{}
        _=>return,
    }
    let obj=value.as_object().unwrap();

    let hinted=if key_hint.to_uppercase().starts_with("REQ-"){Some(key_hint.to_string())}else{None};
    let node_id=truthy_field(obj,"req_id").map(python_str)
        .or_else(||truthy_field(obj,"requirement_id").map(python_str))
        .or_else(||truthy_field(obj,"id").map(python_str))
        .or(hinted)
        .unwrap_or_default()
        .trim()
        .to_string();
    let looks_like=truthy_field(obj,"req_id").is_some()
        ||truthy_field(obj,"requirement_id").is_some()
        ||node_id.to_uppercase().starts_with("REQ-")
        ||matches!(truthy_field(obj,"type").and_then(|v|v.as_str()),
            Some("ATOMIC")|Some("COMPOSITE")|Some("atomic")|Some("composite"));

    let mut current_parent:Option<String>=parent_id.map(str::to_string);
    if looks_like{
        let node_id=if node_id.is_empty(){format!("REQ-{}",out.len()+1)}else{node_id};
        let name=truthy_field(obj,"name").map(python_str)
            .or_else(||truthy_field(obj,"title").map(python_str))
            .or_else(||truthy_field(obj,"label").map(python_str))
            .unwrap_or_else(||node_id.clone());
        let description=truthy_field(obj,"description").map(python_str)
            .or_else(||truthy_field(obj,"desc").map(python_str))
            .or_else(||truthy_field(obj,"content").map(python_str))
            .or_else(||truthy_field(obj,"requirement").map(python_str))
            .unwrap_or_else(||name.clone());
        let scenarios=match obj.get("scenarios"){
            Some(Value::Array(a))=>Some(a.clone()),
            _=>None,
        };
        let dependencies=match obj.get("dependencies"){
            Some(Value::Array(a))=>a.clone(),
            _=>Vec::new(),
        };
        let children=truthy_field(obj,"children").or_else(||truthy_field(obj,"children_ids"));
        let children_ids=match children{
            Some(Value::Array(items))=>items.iter().filter_map(|child|{
                let o=child.as_object()?;
                truthy_field(o,"req_id")
                    .or_else(||truthy_field(o,"requirement_id"))
                    .or_else(||truthy_field(o,"id"))
                    .map(python_str)
            }).collect(),
            _=>Vec::new(),
        };

        if !seen.contains(&node_id){
            out.push(Requirement{
                id:node_id.clone(),
                name,
                description,
                scenarios,
                parent_id:parent_id.map(str::to_string),
                children_ids,
                dependencies,
            });
            seen.insert(node_id.clone());
        }
        current_parent=Some(node_id);
    }

    for (key,child) in obj{
        if matches!(key.as_str(),"scenarios"|"steps"|"dependencies"|"visual_reference"){
            continue;
        }
        if child.is_object()||child.is_array(){
            visit(child,current_parent.as_deref(),key,out,seen);
        }
    }
}

fn collect_entries(dir:&Path)->Vec<String>{
    let mut out=Vec::new();
    collect_entries_into(dir,dir,&mut out);
    out
}

fn collect_entries_into(root:&Path,dir:&Path,out:&mut Vec<String>){
    let Ok(entries)=fs::read_dir(dir) else{return};
    for entry in entries.flatten(){
        let path=entry.path();
        let Ok(rel)=path.strip_prefix(root) else{continue};
        let parts:Vec<String>=rel.components()
            .map(|c|c.as_os_str().to_string_lossy().into_owned())
            .collect();
        if parts.len()>2{
            continue;
        }
        if parts.iter().any(|p|p.starts_with('.')){
            continue;
        }
        out.push(rel.to_string_lossy().into_owned());
        if path.is_dir(){
            collect_entries_into(root,&path,out);
        }
    }
}

pub fn normalize(path:&Path)->PathBuf{
    let mut out=PathBuf::new();
    for component in path.components(){
        match component{
            Component::CurDir=>{}
            Component::ParentDir=>{out.pop();},
            other=>out.push(other.as_os_str()),
        }
    }
    out
}

fn is_truthy(value:&Value)->bool{
    match value{
        Value::Null=>false,
        Value::Bool(b)=>*b,
        Value::Number(n)=>n.as_f64().map_or(true,|f|f!=0.0),
        Value::String(s)=>!s.is_empty(),
        Value::Array(a)=>!a.is_empty(),
        Value::Object(o)=>!o.is_empty(),
    }
}

fn truthy_field<'a>(obj:&'a Map<String,Value>,key:&str)->Option<&'a Value>{
    obj.get(key).and_then(|v|if is_truthy(v){Some(v)}else{None})
}

fn python_str(value:&Value)->String{
    match value{
        Value::String(s)=>s.clone(),
        Value::Null=>"None".to_string(),
        Value::Bool(b)=>if *b{"True".to_string()}else{"False".to_string()},
        other=>other.to_string(),
    }
}

fn arg_str(args:&Value,key:&str)->String{
    match args.get(key){
        Some(v) if is_truthy(v)=>python_str(v),
        _=>String::new(),
    }
}

