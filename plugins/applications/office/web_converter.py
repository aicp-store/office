import re
import requests
from pathlib import Path
from urllib.parse import urljoin, urlparse

PROJECT = Path(__file__).parent.name


# ==================== Noise Filter Rules ====================

NOISE_CLASS_PATTERNS = [
    r'nav', r'menu', r'sidebar', r'footer', r'header', r'banner',
    r'advertisement', r'ad-', r'ads-', r'^ad$', r'^ads$',
    r'popup', r'modal', r'overlay',
    r'comment', r'reply', r'thread',
    r'share', r'social', r'follow', r'subscribe',
    r'related', r'recommend', r'suggestion', r'hot-?article', r'trending',
    r'tag', r'category', r'breadcrumb', r'crumb',
    r'widget', r'toolbar', r'tool-?bar',
    r'copyright', r'disclaimer', r'notice',
    r'login', r'register', r'sign-?in', r'sign-?up',
    r'pagination', r'page-?nav',
    r'toc', r'table-?of-?content',
    r'search', r'archive',
]

REMOVE_TAGS = [
    'script', 'style', 'nav', 'footer', 'header', 'aside',
    'noscript', 'iframe', 'form', 'button', 'select',
    'svg', 'canvas', 'video', 'audio', 'embed', 'object',
]

MAX_LLM_CHARS = 6000
MIN_CHARS_FOR_LLM = 400


def should_remove_element(element):
    from bs4 import Tag

    if not isinstance(element, Tag):
        return False

    tag_name = element.name.lower() if element.name else ''
    if tag_name in REMOVE_TAGS:
        return True

    class_str = ' '.join(element.get('class', []))
    id_str = element.get('id', '')

    for pattern in NOISE_CLASS_PATTERNS:
        if re.search(pattern, class_str, re.I) or re.search(pattern, id_str, re.I):
            return True

    role = element.get('role', '')
    if role in ['navigation', 'banner', 'contentinfo', 'complementary', 'search']:
        return True

    if element.get('hidden') is not None or element.get('aria-hidden') == 'true':
        return True

    return False


def clean_element(element):
    from bs4 import Tag

    if not isinstance(element, Tag):
        return

    for child in list(element.children):
        if isinstance(child, Tag):
            if should_remove_element(child):
                child.decompose()
            else:
                clean_element(child)
                if child.name not in ['img', 'br', 'hr', 'input']:
                    text_content = child.get_text(strip=True)
                    if not text_content and not child.find_all(['img', 'svg']):
                        child.decompose()


def extract_main_content(soup):
    for selector in ['main', 'article', '[role="main"]']:
        el = soup.select_one(selector)
        if el:
            return el

    for pattern in [
        r'post-?body', r'article-?body', r'post-?content', r'article-?content',
        r'entry-?content', r'story-?body', r'news-?content', r'detail-?content',
        r'^content$', r'^post$', r'^article$',
    ]:
        el = soup.find(class_=re.compile(pattern, re.I))
        if el:
            return el

    best_candidate = None
    best_score = 0

    for div in soup.find_all(['div', 'section', 'article']):
        paragraphs = div.find_all('p')
        if len(paragraphs) < 3:
            continue

        text_len = sum(len(p.get_text(strip=True)) for p in paragraphs)
        link_text_len = sum(len(a.get_text(strip=True)) for a in div.find_all('a'))

        if text_len > 0:
            link_ratio = link_text_len / text_len
        else:
            link_ratio = 1.0

        if link_ratio > 0.5:
            continue

        score = text_len * (1 - link_ratio)
        if score > best_score:
            best_score = score
            best_candidate = div

    if best_candidate:
        return best_candidate

    return soup.body if soup.body else soup


# ==================== Core Logic ====================

def get_images_dir(agent):
    candidate = Path(__file__).parent.parent.parent / "www" / PROJECT / "images"
    if candidate.parent.exists():
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    data_root = Path(agent.data_dir).parent
    candidate2 = data_root / "www" / PROJECT / "images"
    candidate2.mkdir(parents=True, exist_ok=True)
    return candidate2


def extract_text_content(soup):
    for tag in soup.find_all(REMOVE_TAGS):
        tag.decompose()

    main = extract_main_content(soup)
    clean_element(main)

    lines = []

    for element in main.descendants:
        if element.name in ['p', 'div', 'section', 'article', 'blockquote']:
            text = element.get_text(strip=True)
            if text and len(text) > 5:
                lines.append(text)
        elif element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            level = int(element.name[1])
            prefix = '#' * level
            text = element.get_text(strip=True)
            if text:
                lines.append(f"{prefix} {text}")
        elif element.name == 'li':
            text = element.get_text(strip=True)
            if text:
                lines.append(f"- {text}")
        elif element.name == 'img':
            src = element.get('src', '') or element.get('data-src', '')
            alt = element.get('alt', '')
            if src and not src.startswith('data:'):
                lines.append(f"[Image: {alt or 'image'}]")

    deduped = []
    for line in lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)

    return '\n\n'.join(deduped)


def extract_title(soup):
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text().strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text().strip()
    return "Untitled"


# ==================== Compression before LLM ====================

NOISE_LINE_PATTERNS = [
    r'^\s*责任编辑[：:].*$',
    r'^\s*海量资讯[、，].*$',
    r'^\s*(VIP课程|APP专享).*$',
    r'^\s*加载中\.\.\.\s*$',
    r'^\s*(上一页|下一页)\s*$',
    r'^\s*\d+/\d+\s*$',
    r'^\s*(分享|举报|收藏|点赞|评论\s*\d*|阅读\s*\d+)\s*$',
    r'^\s*(相关阅读|热门推荐|猜你喜欢|为你推荐|点击加载更多|展开全文|阅读全文)\s*$',
    r'^\s*(7X24小时|交易提示|操盘必读|股市直播|财经头条|商品行情|外汇计算器|基金净值|最新公告|限售解禁|数据中心|条件选股|千股千评|个股诊断|大宗交易|业绩预告).*$',
    r'^\s*(徐小明|凯恩斯|占豪|花荣|wu2198|叶檀|曹中铭|股民大张|宇辉战舰|杨伟民|温彬|余华莘|李德林|李庚南|程实).*$',
    r'^\s*\d{2}/\d{2}\s.*$',
    r'^\s*\d{2}-\d{2}\s.*$',
    r'^\s*来源[：:]\s*\S+$',
    r'^\s*原特斯拉.*$',
    r'^\s*重磅.*$',
    r'^\s*BJ30.*$',
    r'^\s*韩泰.*$',
    r'^\s*央视曝光.*$',
    r'^\s*2026\s*款.*$',
    r'^\s*王朝网.*$',
    r'^\s*DeepMind.*$',
    r'^\s*乘联分会.*$',
    r'^\s*月薪从.*$',
]


def compress_for_llm(raw_text):
    lines = raw_text.split('\n')
    kept = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            kept.append('')
            continue

        if any(re.match(p, stripped, re.I) for p in NOISE_LINE_PATTERNS):
            continue

        if len(stripped) < 15 and not stripped.startswith('#') and not stripped.startswith('-'):
            if not re.match(r'^[A-Z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff\s]{3,}$', stripped):
                continue

        kept.append(stripped)

    result = '\n'.join(kept)
    result = re.sub(r'\n{3,}', '\n\n', result)
    result = result.strip()

    if len(result) > MAX_LLM_CHARS:
        split_point = int(MAX_LLM_CHARS * 0.75)
        head = result[:split_point]
        tail = result[split_point:MAX_LLM_CHARS]
        tail_lines = tail.split('\n')
        tail_kept = [l for l in tail_lines if len(l.strip()) > 40 or l.strip() == '']
        result = head + '\n' + '\n'.join(tail_kept)

    return result[:MAX_LLM_CHARS]


# ==================== Rule-based fallback ====================

def rule_based_cleanup(raw_text, title, url):
    lines = raw_text.split('\n')
    cleaned = []
    found_noise_section = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append('')
            continue

        is_noise = any(re.match(p, stripped, re.I) for p in NOISE_LINE_PATTERNS)
        if is_noise:
            found_noise_section = True

        if found_noise_section:
            if len(stripped) > 60 and not any(re.match(p, stripped, re.I) for p in NOISE_LINE_PATTERNS):
                found_noise_section = False
                cleaned.append(stripped)
            continue

        cleaned.append(stripped)

    result = '\n\n'.join(cleaned)
    result = re.sub(r'\n{3,}', '\n\n', result)

    return f"# {title}\n\n> Source: {url}\n\n{result}"


# ==================== LLM path ====================

LLM_PROMPT = """You are a professional editor. Given raw text extracted from a news article webpage, produce a clean, well-structured Markdown article.

Rules:
1. REMOVE all noise: advertisements, navigation, "related articles", "recommended reading", "hot topics", stock tickers, author name lists, pagination, social media handles, app download prompts, and any content that is clearly NOT part of the article.

2. Pay special attention to the END of the text — websites often append lists of unrelated article links. These are noise. DELETE them entirely.

3. KEEP only: the article title, subtitle, all body paragraphs, direct quotes, and [Image: ...] markers.

4. Structure as clean Markdown:
   - # for main title
   - ## for section headings
   - - for bullet points
   - > for blockquotes
   - Preserve [Image: ...] markers as-is

5. Do NOT summarize. Preserve original meaning and details. Just remove the garbage.

6. Output ONLY the Markdown. No explanations, no preambles.

Raw text:
---
{raw_text}
---"""


async def llm_cleanup(agent, raw_text, title, url):
    llm = agent.llm
    if not llm:
        return None

    compressed = compress_for_llm(raw_text)
    agent.log.info(f"LLM input: {len(raw_text)} → {len(compressed)} chars after compression")

    try:
        prompt = LLM_PROMPT.format(raw_text=compressed)
        result = await llm.chat([{"role": "user", "content": prompt}])
        agent.log.info(f"LLM output: {len(result)} chars")

        if "Source:" not in result and url not in result[:300]:
            result = f"> Source: {url}\n\n{result}"

        return result.strip()
    except Exception as e:
        agent.log.warning(f"LLM cleanup failed: {e}")
        return None


# ==================== Main Entry ====================

async def execute(envelop, agent):
    payload = envelop.payload.get("payload", envelop.payload)
    url = payload.get("url", "")

    if not url:
        envelop.payload = {"error": "url required"}
        return envelop

    images_dir = get_images_dir(agent)

    for f in images_dir.glob("*"):
        try:
            f.unlink()
        except Exception:
            pass

    try:
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding or "utf-8"
        html = resp.text

        soup = BeautifulSoup(html, "html.parser")
        raw_text = extract_text_content(soup)
        page_title = extract_title(soup)

        agent.log.info(f"Web extracted {len(raw_text)} chars from {url}")

        md_content = None
        if len(raw_text) >= MIN_CHARS_FOR_LLM and agent.llm:
            md_content = await llm_cleanup(agent, raw_text, page_title, url)

        if not md_content:
            agent.log.info("Using rule-based fallback")
            md_content = rule_based_cleanup(raw_text, page_title, url)

        file_type = "Web Page"

        safe_name = re.sub(r'[<>:"/\\|?*]', '_', page_title)[:50]
        md_dir = Path(agent.data_dir) / PROJECT
        md_dir.mkdir(parents=True, exist_ok=True)
        md_path = md_dir / f"{safe_name}.md"
        md_path.write_text(md_content, encoding="utf-8")

        images = [f.name for f in images_dir.glob("*")] if images_dir.exists() else []

        envelop.payload = {
            "ok": True,
            "md_content": md_content,
            "file_type": file_type,
            "original_name": page_title,
            "md_path": str(md_path),
            "images": images,
            "images_dir": str(images_dir),
        }
        return envelop

    except requests.RequestException as e:
        envelop.payload = {"error": f"Failed to fetch URL: {str(e)}"}
        return envelop
    except Exception as e:
        agent.log.error(f"Web conversion error: {e}")
        envelop.payload = {"error": f"Conversion failed: {str(e)}"}
        return envelop