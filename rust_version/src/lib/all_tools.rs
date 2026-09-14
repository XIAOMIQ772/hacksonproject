use async_openai::{self, types::chat::{ChatCompletionTool, ChatCompletionTools, FunctionObject}};
use serde_json::json;
pub fn get_tools() -> Vec<ChatCompletionTools>{
    vec![
        ChatCompletionTools::Function(ChatCompletionTool { function: FunctionObject
        {
            name:"bash".into(),
            description:Some("在 bash 中执行命令，返回合并的 stdout/stderr。长时间任务放后台运行.".into()),
            parameters:Some(json!({
                "type": "object",
                "properties": {"command": {"type": "string", "description": "要执行的命令"}},
                "required": ["command"],})),
            strict:None
        }
        }),
        ChatCompletionTools::Function(ChatCompletionTool { function: FunctionObject
        {
            name:"read".into(),
            description:Some("读文件，带行号返回。路径是目录则列出内容。大文件用 offset/limit 分段读。".into()),
            parameters:Some(json!({
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "绝对路径"},
                    "offset": {"type": "integer", "description": "起始行号，从 1 开始"},
                    "limit": {"type": "integer", "description": "读取行数"},
                },
                "required": ["path"],
            })),
            strict:None
        }
        }),
        ChatCompletionTools::Function(ChatCompletionTool { function: FunctionObject
        {
            name:"write".into(),
            description:Some("写入文件，已存在则覆盖，父目录自动创建。".into()),
            parameters:Some(json!({
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "绝对路径"},
                    "content": {"type": "string", "description": "完整文件内容"},
                },
                "required": ["path", "content"],
            })),
            strict:None
        }
        }),
        ChatCompletionTools::Function(ChatCompletionTool { function: FunctionObject
        {
            name:"edit".into(),
            description:Some("替换文件中的一段文本。old 必须在文件中唯一出现，否则替换失败。".into()),
            parameters:Some(json!({
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "绝对路径"},
                    "old": {"type": "string", "description": "要替换的原文，需唯一"},
                    "new": {"type": "string", "description": "替换后的文本"},
                },
                "required": ["path", "old", "new"],
            })),
            strict:None
        }
        })
        ]
}