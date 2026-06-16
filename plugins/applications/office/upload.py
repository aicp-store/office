import core
from pathlib import Path
from zipfile import ZipFile
import tempfile

PROJECT = Path(__file__).parent.name


async def execute(envelop, agent):
    payload = envelop.payload.get("payload", envelop.payload)
    action = payload.get("action", "")

    if action == "upload":
        file_path = payload.get("file_path", "")

        result = await agent.system.call(core.Envelop(
            sender=f"applications/{PROJECT}/upload",
            receiver=f"applications/{PROJECT}/converter",
            payload={"file_path": file_path},
        ))

        envelop.payload = result.payload if result else {"error": "Conversion returned no result"}
        return envelop

    elif action == "fetch_url":
        url = payload.get("url", "")

        result = await agent.system.call(core.Envelop(
            sender=f"applications/{PROJECT}/upload",
            receiver=f"applications/{PROJECT}/web_converter",
            payload={"url": url},
        ))

        envelop.payload = result.payload if result else {"error": "Web conversion returned no result"}
        return envelop

    elif action == "download_zip":
        md_content = payload.get("md_content", "")
        original_name = payload.get("original_name", "document")
        images_dir = payload.get("images_dir", "")

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        zip_path = tmp.name
        tmp.close()

        stem = Path(original_name).stem
        with ZipFile(zip_path, "w") as zf:
            zf.writestr(f"{stem}.md", md_content)
            images_p = Path(images_dir)
            if images_p.exists():
                for img_file in images_p.glob("*"):
                    zf.write(img_file, f"images/{img_file.name}")

        with open(zip_path, "rb") as f:
            envelop.meta["static_content"] = f.read()
        envelop.meta["content_type"] = "application/zip"
        envelop.meta["content_disposition"] = f'attachment; filename="{stem}_md.zip"'

        try:
            Path(zip_path).unlink()
        except Exception:
            pass

        return envelop

    else:
        envelop.payload = {"error": f"Unknown action: {action}"}
        return envelop