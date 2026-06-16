import core
import webbrowser

async def execute(envelop, agent):
    p = envelop.payload
    if "payload" in p and isinstance(p["payload"], dict):
        p = p["payload"]
    
    action = p.get("action", "init")
    parts = envelop.receiver.split("/")
    project = parts[1] if len(parts) > 1 else "office"

    if action == "init":
        await agent.system.call(core.Envelop(
            sender=f"applications/{project}/_init",
            receiver="shell/_tray",
            payload={
                "action": "add_menu",
                "app_id": project,
                "label": "🧰 工具箱",
                "items": [
                    {"label": "🧠 思维导图", "action": "mindmap", "receiver": f"applications/{project}/_init"},
                    {"label": "📝 文本转MD", "action": "text_to_md", "receiver": f"applications/{project}/_init"},
                    {"label": "📄 富文本编辑器", "action": "text_processor", "receiver": f"applications/{project}/_init"},
                    {"label": "📑 文档转MD", "action": "office2md", "receiver": f"applications/{project}/_init"},
                    {"label": "📦 项目分析", "action": "project2md", "receiver": f"applications/{project}/_init"},
                ],
            },
        ))
        envelop.payload = {"ok": True}
        return envelop

    elif action == "mindmap":
        webbrowser.open(f"{agent.base_url}/{project}/aicp-mind.html")
        return envelop

    elif action == "text_to_md":
        webbrowser.open(f"{agent.base_url}/{project}/text_to_md.html")
        return envelop

    elif action == "text_processor":
        webbrowser.open(f"{agent.base_url}/{project}/text-processor.html")
        return envelop

    elif action == "office2md":
        webbrowser.open(f"{agent.base_url}/{project}/office2md.html")
        return envelop

    elif action == "project2md":
        webbrowser.open(f"{agent.base_url}/{project}/project2md.html")
        return envelop

    else:
        envelop.payload = {"error": f"Unknown action: {action}"}
        return envelop