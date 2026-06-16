def help():
    return {
        "route": "/api/text/process",
        "input": {
            "text": "原始文字",
            "action": "summary|abstract|expand|polish|translate|outline",
            "style": "商务|学术|通俗|正式（可选）",
            "target_lang": "目标语言（translate时用）",
            "ratio": "扩写比例 1.5|2|3（expand时用）"
        },
        "output": {"result": "处理后的文字"},
        "description": "文字处理：摘要、扩写、润色、翻译、生成大纲"
    }

async def execute(envelop, agent):
    try:
        text = envelop.payload.get("text", "")
        action = envelop.payload.get("action", "summary")
        style = envelop.payload.get("style", "正式")
        target_lang = envelop.payload.get("target_lang", "中文")
        ratio = envelop.payload.get("ratio", 2)
        
        if not text:
            envelop.payload = {"error": "No text provided"}
            return envelop
        
        llm = agent.llm
        if not llm:
            envelop.payload = {"error": "LLM not available", "result": text}
            return envelop
        
        prompts = {
            "summary": f"""请将以下文字进行摘要，提取核心要点，用简洁的语言表达。

要求：
- 长度控制在原文的 20% 以内
- 保留关键信息
- 风格：{style}

原文：
{text}

只输出摘要结果，不要其他解释。""",

            "abstract": f"""请为以下文字写一个摘要（abstract），适合放在论文或报告开头。

要求：
- 100-200字
- 说明背景、方法、结论
- 风格：{style}

原文：
{text}

只输出摘要。""",

            "expand": f"""请将以下文字进行扩写，增加细节和例证。

扩写比例：原文的 {ratio} 倍
风格：{style}

原文：
{text}

只输出扩写后的内容。""",

            "polish": f"""请润色以下文字，优化表达，修正语法，保持原意。

润色要求：{style}

原文：
{text}

只输出润色后的内容。""",

            "translate": f"""请将以下文字翻译成 {target_lang}。

翻译要求：准确、流畅、符合 {target_lang} 表达习惯

原文：
{text}

只输出翻译结果。""",

            "outline": f"""请为以下文字生成 PPT 大纲，每页一个主题。

输出格式：
## 标题
- 要点1
- 要点2

原文：
{text}

只输出大纲。""",

            "ppt_ready": f"""请将以下文字转换成可以直接用于 PPT 的格式。

要求：
- 每页一个主题，用 ===SLIDE=== 分隔
- 每页包含：标题 + 3-5 个要点
- 风格：{style}

原文：
{text}

示例输出：
===SLIDE===
## 标题
- 要点1
- 要点2
===SLIDE===
## 第二个标题
- 要点1
- 要点2

只输出这种格式。"""
        }
        
        prompt = prompts.get(action, prompts["summary"])
        
        result = await llm.chat([
            {"role": "system", "content": "你是一个专业的文字处理助手，只输出处理后的内容，不要添加解释。"},
            {"role": "user", "content": prompt}
        ])
        
        envelop.payload = {"result": result.strip(), "action": action}
        return envelop
        
    except Exception as e:
        envelop.payload = {"error": str(e)}
        return envelop