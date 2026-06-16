def help():
    return {
        "route": "/api/mind/generate",
        "input": {"text": "用户输入的主题"},
        "output": {"tree": {"text": "根", "children": [...]}},
        "description": "AI 生成标准思维导图结构"
    }

import json

async def execute(envelop, agent):
    try:
        text = envelop.payload.get("text", "")
        if not text:
            envelop.payload = {"error": "No text provided"}
            return envelop
        
        llm = agent.llm
        if not llm:
            envelop.payload = {"tree": {"text": text, "children": [
                {"text": "子主题1", "children": [{"text": "细节1"}, {"text": "细节2"}]},
                {"text": "子主题2", "children": [{"text": "细节3"}, {"text": "细节4"}]},
                {"text": "子主题3", "children": [{"text": "细节5"}, {"text": "细节6"}]}
            ]}}
            return envelop
        
        prompt = f"""将以下内容生成标准思维导图JSON格式。这是一个严格的树形结构，每个节点只有一个父节点。

内容：{text}

要求：
1. 根节点是核心主题
2. 根据内容复杂度，合理生成子节点
3. 每个节点必须有 text 字段，children 是数组

只输出JSON，不要其他内容。"""

        result = await llm.chat([
            {"role": "system", "content": "你是思维导图专家，只输出JSON。"},
            {"role": "user", "content": prompt}
        ])
        
        result = result.strip()
        if result.startswith("```json"):
            result = result[7:]
        if result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]
        
        tree = json.loads(result)
        envelop.payload = {"tree": tree}
        return envelop
    except Exception as e:
        envelop.payload = {"error": str(e)}
        return envelop