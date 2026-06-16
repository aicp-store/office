import re
import json
import subprocess
import asyncio
from pathlib import Path

PROJECT = Path(__file__).parent.name

# ==================== Config ====================

CODE_EXTENSIONS = {
    '.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java',
    '.c', '.cpp', '.h', '.hpp', '.cs', '.rb', '.php', '.swift',
    '.kt', '.scala', '.sh', '.bash', '.zsh', '.ps1', '.toml',
}

CONFIG_FILES = {
    'package.json', 'Cargo.toml', 'go.mod', 'requirements.txt',
    'Pipfile', 'pyproject.toml', 'Makefile', 'Dockerfile',
    'docker-compose.yml', '.env.example', 'tsconfig.json',
}

DOC_FILES = {
    'README.md', 'readme.md', 'README', 'CHANGELOG.md',
    'CONTRIBUTING.md', 'LICENSE', 'ARCHITECTURE.md',
}

SKIP_DIRS = {
    '.git', '__pycache__', 'node_modules', 'venv', '.venv',
    'vendor', '.idea', '.vscode', 'dist', 'build', 'target',
    '.next', '.nuxt', 'coverage', '.pytest_cache', '.mypy_cache',
    'egg-info', '.tox', '.eggs', '.git',
}


MAX_FILES_TO_ANALYZE = 500


# ==================== Helpers ====================

def get_language_name(ext):
    mapping = {
        '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript',
        '.tsx': 'React TSX', '.jsx': 'React JSX', '.go': 'Go',
        '.rs': 'Rust', '.java': 'Java', '.c': 'C', '.cpp': 'C++',
        '.rb': 'Ruby', '.php': 'PHP', '.swift': 'Swift', '.kt': 'Kotlin',
        '.scala': 'Scala', '.sh': 'Shell', '.cs': 'C#',
    }
    return mapping.get(ext, ext.lstrip('.').upper())


def should_skip_path(path, root):
    parts = path.relative_to(root).parts
    for part in parts:
        if part in SKIP_DIRS or part.startswith('.'):
            return True
        if 'venv' in part.lower() or 'virtualenv' in part.lower():
            return True
    return False


def read_head(filepath, lines=30):
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return ''.join(f.readline() for _ in range(lines))
    except Exception:
        return ''


def get_project_dir(agent):
    d = Path(agent.data_dir) / PROJECT / "github_repos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_cache_path(agent, key):
    import hashlib
    h = hashlib.md5(key.encode()).hexdigest()[:12]
    d = Path(agent.data_dir) / PROJECT / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{h}.json"


def load_cache(agent, key):
    p = get_cache_path(agent, key)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            pass
    return None


def save_cache(agent, key, data):
    p = get_cache_path(agent, key)
    safe = {
        'md_content': data.get('md_content', ''),
        'tree': data.get('tree', {}),
        'file_type': data.get('file_type', ''),
        'original_name': data.get('original_name', ''),
    }
    p.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding='utf-8')


def is_github_url(s):
    return bool(re.match(r'^https?://github\.com/[^/]+/[^/]+', s))


async def clone_repo(url, target_dir, agent):
    if target_dir.exists():
        try:
            subprocess.run(['git', '-C', str(target_dir), 'pull', '--depth=1'],
                           capture_output=True, timeout=30)
            agent.log.info(f"Pulled: {url}")
            return True
        except Exception:
            import shutil
            shutil.rmtree(target_dir, ignore_errors=True)

    try:
        subprocess.run(['git', 'clone', '--depth=1', url, str(target_dir)],
                       capture_output=True, timeout=60, check=True)
        agent.log.info(f"Cloned: {url} → {target_dir}")
        return True
    except Exception as e:
        agent.log.error(f"Clone failed: {e}")
        return False


# ==================== Progress broadcast ====================

async def broadcast_progress(agent, scan_id, stage, percent, message):
    try:
        import core
        await agent.system.call(core.Envelop(
            sender=f"applications/{PROJECT}/folder_scan",
            receiver="os/_websocket",
            payload={
                "action": "push",
                "channel_id": f"room_project2md_{scan_id}",
                "data": {
                    "type": "progress",
                    "msg": message,
                    "step": stage,
                    "percent": percent,
                    "scan_id": scan_id,
                }
            }
        ))
    except Exception as e:
        agent.log.warning(f"Broadcast failed: {e}")


# ==================== Scanning ====================

def scan_directory(root_path, agent):
    root = Path(root_path)
    if not root.exists():
        return None

    info = {
        'project_name': root.name,
        'languages': {},
        'total_files': 0,
        'total_lines': 0,
        'readme': '',
        'config_files': [],
        'files': [],
        'tree': {'text': root.name, 'children': []},
    }

    all_files = []
    for f in root.rglob('*'):
        if not f.is_file() or should_skip_path(f, root):
            continue
        all_files.append(f)

    all_files.sort(key=lambda f: (
        not (f.name in DOC_FILES),
        not (f.name in CONFIG_FILES),
        not (f.suffix in CODE_EXTENSIONS),
        str(f),
    ))

    files_to_scan = all_files[:MAX_FILES_TO_ANALYZE]
    agent.log.info(f"Scan: {root} → {len(files_to_scan)}/{len(all_files)} files")

    for idx, filepath in enumerate(files_to_scan):
        try:
            line_count = sum(1 for _ in open(filepath, 'r', encoding='utf-8', errors='ignore'))
        except Exception:
            line_count = 0

        info['total_files'] += 1
        info['total_lines'] += line_count
        rel_path = str(filepath.relative_to(root)).replace('\\', '/')

        if filepath.suffix in CODE_EXTENSIONS:
            lang = get_language_name(filepath.suffix)
            info['languages'][lang] = info['languages'].get(lang, 0) + 1

        if filepath.name.lower() in DOC_FILES and not info['readme']:
            try:
                info['readme'] = filepath.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                pass

        if filepath.name in CONFIG_FILES:
            info['config_files'].append({
                'name': filepath.name, 'path': rel_path,
                'content': read_head(filepath, 50)[:2000],
            })

        is_key = (
            filepath.suffix in CODE_EXTENSIONS and
            (filepath.name in ('main.py', 'main.go', 'main.rs', 'index.js', 'index.ts',
                               'app.py', 'server.py', 'server.go', 'lib.rs') or
             'main' in filepath.stem.lower() or 'index' in filepath.stem.lower() or
             'app' in filepath.stem.lower() or line_count > 100)
        )
        if is_key:
            info['files'].append({
                'path': rel_path,
                'lang': get_language_name(filepath.suffix),
                'lines': line_count,
                'content': read_head(filepath, 40),
            })

    return info


def build_file_tree(info):
    root_node = {'text': info['project_name'], 'children': []}
    dir_nodes = {'': root_node}

    for f in info.get('files', []):
        parts = f['path'].split('/')
        for i in range(len(parts) - 1):
            dir_path = '/'.join(parts[:i+1])
            if dir_path not in dir_nodes:
                parent_path = '/'.join(parts[:i])
                parent = dir_nodes.get(parent_path, root_node)
                node = {'text': '📁 ' + parts[i], 'children': []}
                parent['children'].append(node)
                dir_nodes[dir_path] = node

        dir_path = '/'.join(parts[:-1])
        parent = dir_nodes.get(dir_path, root_node)
        node = {'text': f'{parts[-1]} ({f["lines"]}L {f["lang"]})', 'children': []}
        parent['children'].append(node)

    return root_node


# ==================== LLM ====================

LLM_README_PROMPT = """One sentence summary (under 20 words) of what this project does:

{text}

Summary:"""

LLM_FILE_PROMPT = """What does this file do? One short phrase (under 10 words):

File: {filename} ({lang})
{code}

Summary:"""

LLM_CONFIG_PROMPT = """One phrase summary of this config:

File: {filename}
{content}

Summary:"""


async def summarize_all(agent, info, scan_id):
    llm = agent.llm
    if not llm:
        return '', {}, {}

    readme_summary = ''
    file_summaries = {}
    config_summaries = {}

    # README
    if info['readme']:
        await broadcast_progress(agent, scan_id, "llm", 60, "🤖 分析 README...")
        try:
            p = LLM_README_PROMPT.format(text=info['readme'][:1500])
            r = await llm.chat([{"role": "user", "content": p}])
            readme_summary = r.strip().strip('"').strip("'")
        except Exception:
            pass

    # Config files
    configs = info.get('config_files', [])[:5]
    for idx, c in enumerate(configs):
        pct = 65 + int((idx / max(len(configs), 1)) * 5)
        await broadcast_progress(agent, scan_id, "llm", pct, f"🤖 分析配置: {c['name']}")
        try:
            p = LLM_CONFIG_PROMPT.format(filename=c['name'], content=c['content'][:800])
            r = await llm.chat([{"role": "user", "content": p}])
            config_summaries[c['name']] = r.strip().strip('"').strip("'")
        except Exception:
            pass

    # Key files
    key_files = info['files'][:15]
    for idx, f in enumerate(key_files):
        pct = 70 + int((idx / len(key_files)) * 15)
        await broadcast_progress(agent, scan_id, "llm", pct, f"🤖 分析: {f['path']}")
        try:
            p = LLM_FILE_PROMPT.format(
                filename=f['path'], lang=f['lang'], code=f['content'][:1000])
            r = await llm.chat([{"role": "user", "content": p}])
            file_summaries[f['path']] = r.strip().strip('"').strip("'")
        except Exception:
            pass

    return readme_summary, file_summaries, config_summaries


def build_architecture_tree(info):
    files = info.get('files', [])
    if not files:
        return ''
    
    dirs = {}
    root_name = info['project_name']
    
    for f in files:
        parts = f['path'].split('/')
        for i in range(len(parts)):
            dir_path = '/'.join(parts[:i]) if i > 0 else ''
            child = parts[i] + ('/' if i < len(parts) - 1 else '')
            if dir_path not in dirs:
                dirs[dir_path] = set()
            dirs[dir_path].add(child)
    
    ANNOTATIONS = {
        'core': '微内核：Envelop 消息信封',
        'runtime': 'AI 运行时：LLM + 热加载',
        'plugins': '插件系统',
        'plugins/os': '系统服务：HTTP/WS/文件/调度',
        'plugins/shell': 'Shell 层：托盘/通知/输入',
        'plugins/builtins': '内置应用',
        'plugins/builtins/mk': '全局快捷键与魔法功能',
        'plugins/builtins/screen_probe': '屏幕探测',
        'plugins/builtins/studio': 'IDE 框架',
        'plugins/builtins/llm_web': 'LLM Web 窗口',
        'plugins/builtins/agents': 'AI Agent',
        'plugins/builtins/message_core': '消息核心',
        'plugins/builtins/control': '控制面板',
        'plugins/builtins/system': '系统 GUI',
        'plugins/applications': '用户空间应用',
        'plugins/applications/office': 'Office 五件套',
        'plugins/applications/personal_assistant': '个人助手',
        'plugins/applications/stockai': '股票 AI',
        'plugins/applications/syschecker': '系统诊断',
        'plugins/applications/vidsurg': '视频处理',
        'plugins/applications/hermes': 'Hermes',
        'plugins/auto': '自动化',
        'plugins/eaater': '动态插件生成',
        'data': '数据空间',
        'data/personal_assistant': '个人助手任务快照',
        'data/personal_assistant/tasks': '历史任务 (已折叠)',
        'www': '前端资源',
        'probe-bk': '屏幕探测备份',
    }

    # Fold repetitive subdirs (like personal_assistant_xxx)
    FOLD_PATTERNS = [
        r'personal_assistant_[a-f0-9]+',  # task dirs
    ]
    
    def should_fold(dirname):
        import re
        for pattern in FOLD_PATTERNS:
            if re.match(pattern, dirname):
                return True
        return False
    
    def render_tree(path='', indent='', is_last=True):
        lines = []
        if path not in dirs:
            return lines
        
        children = sorted(dirs[path], key=lambda x: (not x.endswith('/'), x.lower()))
        
        # Check if this dir has many similar subdirs → fold them
        fold_count = 0
        for child in children:
            if child.endswith('/') and should_fold(child.rstrip('/')):
                fold_count += 1
        
        if fold_count >= 10 and path != '':
            # Fold: show one line with count
            lines.append(f"{indent}└── ({fold_count} 个历史任务目录)")
            return lines
        
        # Normal rendering
        for i, child in enumerate(children):
            is_last_child = (i == len(children) - 1)
            connector = '└── ' if is_last_child else '├── '
            
            display_name = child.rstrip('/')
            full_path = (path + '/' + display_name) if path else display_name
            
            anno = ANNOTATIONS.get(full_path, '')
            line = f"{indent}{connector}{display_name}"
            if anno:
                line += f"  ← {anno}"
            lines.append(line)
            
            if child.endswith('/'):
                next_indent = indent + ('    ' if is_last_child else '│   ')
                lines.extend(render_tree(full_path, next_indent, is_last_child))
        
        return lines
    
    lines = [f'{root_name}/']
    top_children = sorted(dirs.get('', set()), key=lambda x: (not x.endswith('/'), x.lower()))
    for i, child in enumerate(top_children):
        is_last = (i == len(top_children) - 1)
        connector = '└── ' if is_last else '├── '
        display_name = child.rstrip('/')
        full_path = display_name
        anno = ANNOTATIONS.get(full_path, '')
        line = f"{connector}{display_name}"
        if anno:
            line += f"  ← {anno}"
        lines.append(line)
        if child.endswith('/'):
            next_indent = '    ' if is_last else '│   '
            lines.extend(render_tree(full_path, next_indent, is_last))
    
    return '\n'.join(lines)


def generate_markdown(info, file_summaries, config_summaries, readme_summary):
    lines = [f"# {info['project_name']}\n"]

    # Stats
    lang_str = ', '.join(f'{l}: {c}' for l, c in sorted(
        info['languages'].items(), key=lambda x: -x[1]))
    lines.append(f"**Files:** {info['total_files']} | **Lines:** {info['total_lines']}")
    if lang_str:
        lines.append(f"**Languages:** {lang_str}")
    lines.append('')

    # Architecture tree
    arch_tree = build_architecture_tree(info)
    if arch_tree:
        lines.append('## 🏗️ Architecture')
        lines.append('')
        lines.append('```')
        lines.append(arch_tree)
        lines.append('```')
        lines.append('')

    # Config files
    if config_summaries:
        lines.append('## ⚙️ Configuration\n')
        for c in info.get('config_files', []):
            s = config_summaries.get(c['name'], '')
            lines.append(f'- **{c["name"]}** — {s}' if s else f'- **{c["name"]}**')
        lines.append('')

    # Key files
    if info.get('files'):
        lines.append('## 📂 Key Files\n')
        for f in info['files']:
            s = file_summaries.get(f['path'], '')
            line = f'- **`{f["path"]}`** ({f["lang"]}, {f["lines"]} 行)'
            if s:
                line += f' — {s}'
            lines.append(line)
        lines.append('')

    # Code stats
    if info['languages']:
        lines.append('## 📊 Code Stats\n')
        lines.append('| Language | Files |')
        lines.append('|----------|-------|')
        for lang, count in sorted(info['languages'].items(), key=lambda x: -x[1]):
            lines.append(f'| {lang} | {count} |')
        lines.append('')

    # README as appendix
    if info.get('readme'):
        lines.append('## 📖 README\n')
        lines.append(info['readme'][:1000])
        lines.append('')

    lines.append(f'\n---\n*Generated by Project2MD*')
    return '\n'.join(lines)


# ==================== Main Entry ====================

async def execute(envelop, agent):
    payload = envelop.payload.get("payload", envelop.payload)
    action = payload.get("action", "scan")

    if action != "scan":
        envelop.payload = {"error": f"Unknown action: {action}"}
        return envelop

    source = payload.get("source", "")
    scan_id = payload.get("scan_id", "default")
    force_refresh = payload.get("force_refresh", False)

    if not source:
        envelop.payload = {"error": "source required"}
        return envelop

    cache_key = source

    if not force_refresh:
        cached = load_cache(agent, cache_key)
        if cached:
            agent.log.info(f"Project2MD: cache hit for {source}")
            await broadcast_progress(agent, scan_id, "done", 100, "✅ 来自缓存")
            envelop.payload = {
                "ok": True,
                "md_content": cached.get('md_content', ''),
                "tree": cached.get('tree', {}),
                "file_type": cached.get('file_type', ''),
                "original_name": cached.get('original_name', ''),
                "from_cache": True,
                "scan_id": scan_id,
            }
            return envelop

    folder_path = None
    project_name = ""

    try:
        # Stage 1: Clone (GitHub only)
        if is_github_url(source):
            await broadcast_progress(agent, scan_id, "clone", 5, "📥 正在拉取代码...")
            repo_name = source.rstrip('/').split('/')[-1].replace('.git', '')
            repos_dir = get_project_dir(agent)
            target_dir = repos_dir / repo_name

            if not await clone_repo(source, target_dir, agent):
                await broadcast_progress(agent, scan_id, "error", 0, "❌ 拉取失败")
                envelop.payload = {"error": f"Failed to clone: {source}"}
                return envelop

            folder_path = target_dir
            project_name = repo_name
            await broadcast_progress(agent, scan_id, "clone", 20, "✅ 代码拉取完成")
        else:
            p = Path(source)
            if not p.exists() or not p.is_dir():
                envelop.payload = {"error": f"Not a valid directory: {source}"}
                return envelop
            folder_path = p
            project_name = p.name
            await broadcast_progress(agent, scan_id, "clone", 20, "📁 本地目录已就绪")

        # Stage 2: Scan files
        await broadcast_progress(agent, scan_id, "scan", 25, "🔍 正在扫描文件...")
        info = scan_directory(folder_path, agent)
        if not info or info['total_files'] == 0:
            await broadcast_progress(agent, scan_id, "error", 0, "❌ 未找到文件")
            envelop.payload = {"error": "No files found"}
            return envelop

        await broadcast_progress(agent, scan_id, "scan", 55,
                                 f"📊 已扫描 {info['total_files']} 个文件, {info['total_lines']} 行代码")

        # Stage 3: LLM analysis
        await broadcast_progress(agent, scan_id, "llm", 60, "🤖 AI 分析 README...")
        readme_summary, file_summaries, config_summaries = await summarize_all(agent, info, scan_id)

        await broadcast_progress(agent, scan_id, "llm", 85,
                                 f"🤖 已分析 {len(file_summaries)} 个关键文件")

        # Stage 4: Build output
        await broadcast_progress(agent, scan_id, "build", 90, "📝 生成文档...")
        md_content = generate_markdown(info, file_summaries, config_summaries, readme_summary)
        tree = build_file_tree(info)

        lang_count = len(info.get('languages', {}))
        file_type = f"Project: {info['total_files']} files, {lang_count} languages"

        md_dir = Path(agent.data_dir) / PROJECT
        md_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', project_name)
        md_path = md_dir / f"{safe_name}_project.md"
        md_path.write_text(md_content, encoding='utf-8')

        result = {
            "ok": True,
            "md_content": md_content,
            "tree": tree,
            "file_type": file_type,
            "original_name": project_name,
            "md_path": str(md_path),
            "images": [],
            "images_dir": "",
            "from_cache": False,
            "scan_id": scan_id,
        }

        save_cache(agent, cache_key, result)

        await broadcast_progress(agent, scan_id, "done", 100, "✅ 分析完成")

        envelop.payload = result
        return envelop

    except Exception as e:
        agent.log.error(f"Project2MD error: {e}")
        await broadcast_progress(agent, scan_id, "error", 0, f"❌ {str(e)}")
        envelop.payload = {"error": f"Scan failed: {str(e)}"}
        return envelop