"""
Версия для деплоя на Streamlit Cloud.
Отличия от app.py (локальная версия):
  - Пути к данным — относительные (рядом с этим файлом).
  - Нет локального HTTP-сервера: на облаке srcdoc-iframe работает через HTTPS-origin.
  - Рендеринг контента через st.components.v1.html() напрямую.
"""

import re
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
import json

from bs4 import BeautifulSoup, NavigableString
from rapidfuzz import fuzz, process

# ──────────────────────────────────────────────
#  ПУТИ К ФАЙЛАМ (относительные — рядом с app_cloud.py)
# ──────────────────────────────────────────────
APP_DIR = Path(__file__).parent

THEORY_JSON_PATH = APP_DIR / "_select_g_name_as_goal_title_gc_content_txt_as_content_from_goal.json"
SKILLS_JSON_PATH = APP_DIR / "oge_tasks.json"

FUZZY_THRESHOLD = 90

# ──────────────────────────────────────────────
#  СТРАНИЦА
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="Теория ОГЭ — математика",
    page_icon="📐",
    layout="wide",
)


# ──────────────────────────────────────────────
#  ЗАГРУЗКА И FUZZY-СОПОСТАВЛЕНИЕ
# ──────────────────────────────────────────────
@st.cache_data(show_spinner="⏳ Загружаем данные…")
def load_data() -> tuple[dict, list]:
    with open(THEORY_JSON_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    items: list[dict] = raw[next(iter(raw))]

    with open(SKILLS_JSON_PATH, encoding="utf-8") as f:
        skills_raw: list[dict] = json.load(f)

    skill_to_num: dict[str, int] = {}
    for s in skills_raw:
        sk, num = s["навык"], s["номер_задания"]
        skill_to_num.setdefault(sk, num)

    skill_names = list(skill_to_num.keys())
    grouped: dict = {}

    for item in items:
        match_result = process.extractOne(
            item["goal_title"], skill_names, scorer=fuzz.ratio
        )
        if match_result and match_result[1] >= FUZZY_THRESHOLD:
            sk  = match_result[0]
            num = skill_to_num[sk]
            item["_oge_num"]       = num
            item["_matched_skill"] = sk
            group_key = num
        else:
            item["_oge_num"]       = None
            item["_matched_skill"] = None
            group_key = "Без номера"

        grouped.setdefault(group_key, []).append(item)

    numeric_keys = sorted(k for k in grouped if isinstance(k, int))
    all_keys     = numeric_keys + (["Без номера"] if "Без номера" in grouped else [])
    return grouped, all_keys


# ──────────────────────────────────────────────
#  ТРАНСФОРМАЦИЯ HTML ДЛЯ ОТОБРАЖЕНИЯ
# ──────────────────────────────────────────────

_IMPORTANT_BIDS = {"14", "17", "18", "20"}
_SPOILER_BIDS   = {"15", "19", "12", "23"}


def transform_content(content_html: str) -> str:
    """
    Преобразует кастомные теги в стандартный HTML.
    TikZ-блоки вставляются через string-replace ПОСЛЕ сериализации BS4,
    чтобы избежать HTML-экранирования LaTeX-кода.
    """
    soup = BeautifulSoup(content_html, "html.parser")

    tikz_slots: dict[str, str] = {}
    for i, tag in enumerate(list(soup.find_all("math-image-block"))):
        tikz_code = tag.get("data-tikz", "")
        slot_id   = f"TIKZSLOT{i}END"
        tikz_slots[slot_id] = tikz_code
        placeholder = soup.new_tag(
            "div", attrs={"class": "tikz-wrap", "data-tikzslot": slot_id}
        )
        tag.replace_with(placeholder)

    for tag in list(soup.find_all("math-block")):
        latex = tag.get("data-latex", "")
        span  = soup.new_tag("span", attrs={"class": "math-inline"})
        span.append(NavigableString(f"\\({latex}\\)"))
        tag.replace_with(span)

    for tag in list(soup.find_all("warning-block")):
        div = soup.new_tag("div", attrs={"class": "warning-block"})
        for child in list(tag.children):
            div.append(child.extract())
        tag.replace_with(div)

    for tag in list(soup.find_all("custom-text-block")):
        bid = tag.get("data-block-id", "x")
        div = soup.new_tag("div", attrs={"class": f"cblock bid-{bid}"})
        for child in list(tag.children):
            div.append(child.extract())
        tag.replace_with(div)

    for tag in list(soup.find_all("text-block")):
        div = soup.new_tag("div", attrs={"class": "text-block"})
        for child in list(tag.children):
            div.append(child.extract())
        tag.replace_with(div)

    for tag in list(soup.find_all("step-divider")):
        tag.replace_with(soup.new_tag("hr", attrs={"class": "step-divider"}))

    # Разворачиваем все спойлеры (details) по умолчанию
    for tag in soup.find_all("details"):
        tag["open"] = ""

    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        classes = [c for c in tag.get("class", []) if "admin-styles" not in c]
        if classes:
            tag["class"] = classes
        elif tag.has_attr("class"):
            del tag["class"]

    html_str = str(soup)

    for slot_id, tikz_code in tikz_slots.items():
        old = f'<div class="tikz-wrap" data-tikzslot="{slot_id}"></div>'
        new = (
            '<div class="tikz-wrap">'
            '<script type="text/tikz">\n'
            + tikz_code +
            '\n</script>'
            '</div>'
        )
        html_str = html_str.replace(old, new)

    return html_str


# ──────────────────────────────────────────────
#  ЭКСПОРТ В ТЕКСТ
# ──────────────────────────────────────────────

def _node_to_text(node) -> str:
    if isinstance(node, NavigableString):
        return str(node)

    name = getattr(node, "name", None)

    if name == "math-block":
        return f"${node.get('data-latex', '')}$"
    if name == "math-image-block":
        return f"\nКАРТИНКА\n{node.get('data-tikz', '')}\nКОНЕЦ КАРТИНКИ\n"
    if name == "br":
        return "\n"

    inner = "".join(_node_to_text(c) for c in node.children)

    if name == "p":
        return inner.strip() + "\n"
    if name in ("h1", "h2", "h3", "h4"):
        return "\n" + inner.strip() + "\n"
    if name == "li":
        return "• " + inner.strip() + "\n"
    if name in ("ul", "ol"):
        return "\n" + inner + "\n"

    return inner


def _block_text(tag) -> str:
    return "".join(_node_to_text(c) for c in tag.children).strip()


def content_to_export_text(content_html: str, title: str) -> str:
    soup  = BeautifulSoup(content_html, "html.parser")
    parts = [title, "=" * max(len(title), 1), ""]

    for child in soup.children:
        if isinstance(child, NavigableString):
            t = str(child).strip()
            if t:
                parts.append(t)
            continue

        name = child.name

        if name == "warning-block":
            inner = _block_text(child)
            if inner:
                parts.append("<важное>")
                parts.append(inner)
                parts.append("<конец важного>")

        elif name == "custom-text-block":
            bid   = child.get("data-block-id", "x")
            inner = _block_text(child)
            if not inner:
                continue
            if bid in _IMPORTANT_BIDS:
                parts.append("<важное>")
                parts.append(inner)
                parts.append("<конец важного>")
            else:
                parts.append(inner)

        elif name == "math-image-block":
            tikz = child.get("data-tikz", "")
            parts.append("КАРТИНКА")
            parts.append(tikz)
            parts.append("КОНЕЦ КАРТИНКИ")

        elif name == "step-divider":
            parts.append("\n" + "─" * 50 + "\n")

        else:
            inner = _block_text(child)
            if inner:
                parts.append(inner)

    return "\n\n".join(p for p in parts if p.strip())


def safe_filename(s: str) -> str:
    s = re.sub(r'[\\/*?:"<>|]', "", s)
    return s.replace("\n", " ").strip()[:80]


# ──────────────────────────────────────────────
#  HTML-ШАБЛОН
# ──────────────────────────────────────────────
_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    padding: 20px 28px 40px;
    color: #1c1c2e;
    line-height: 1.7;
    font-size: 15px;
}
h1 { font-size:1.5em;  color:#1a237e; margin:22px 0 10px }
h2 { font-size:1.3em;  color:#283593; margin:18px 0 8px  }
h3 { font-size:1.15em; color:#303f9f; margin:14px 0 6px  }
h4 { font-size:1.05em; color:#3949ab; margin:12px 0 4px  }
p  { margin: 6px 0 9px }
ul, ol { padding-left:22px; margin:6px 0 9px }
li { margin:3px 0 }
mark { border-radius:3px; padding:1px 5px }

.warning-block {
    border-left:4px solid #f59e0b; background:#fffbeb;
    padding:14px 18px; border-radius:0 8px 8px 0; margin:16px 0;
}
.cblock { margin:14px 0; padding:12px 18px; border-radius:0 6px 6px 0; }
.cblock.bid-14 { background:#eff6ff; border-left:3px solid #3b82f6; }
.cblock.bid-15 { background:none; border-left:none; padding-left:0; }
.cblock.bid-17 { background:#f0fdf4; border-left:3px solid #22c55e; }
.cblock.bid-18 { background:#fdf4ff; border-left:3px solid #a855f7; }
.cblock.bid-19 { background:none; border-left:none; padding-left:0; }
.cblock.bid-20 { background:#ecfeff; border-left:3px solid #06b6d4; }
.cblock.bid-x  { background:none; border-left:none; padding-left:0; }

.text-block { margin:10px 0 }
.step-divider { border:none; border-top:2px dashed #cbd5e1; margin:26px 0 }

.tikz-wrap { text-align:center; margin:20px 0; min-height:40px }
.tikz-wrap svg { max-width:100%; height:auto }

.katex-display { overflow-x:auto; padding:6px 0 }
.math-inline   { display:inline }
"""

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>%%TITLE%%</title>

  <!-- KaTeX -->
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css"
        crossorigin="anonymous">
  <script defer
          src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"
          crossorigin="anonymous"></script>
  <script defer
          src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"
          crossorigin="anonymous"
          onload="renderMathInElement(document.body, {
              delimiters: [
                {left: '\\\\(', right: '\\\\)', display: false},
                {left: '\\\\[', right: '\\\\]', display: true}
              ],
              throwOnError: false
          });"></script>

  <!-- TikZJax -->
  <link rel="stylesheet" href="https://tikzjax.com/v1/fonts.css">
  <script src="https://tikzjax.com/v1/tikzjax.js"></script>

  <style>%%CSS%%</style>
</head>
<body>
%%BODY%%
</body>
</html>
"""


def make_full_html(content_html: str, title: str = "") -> str:
    body = transform_content(content_html)
    return (
        _HTML_TEMPLATE
        .replace("%%TITLE%%", title)
        .replace("%%CSS%%", _CSS)
        .replace("%%BODY%%", body)
    )


# ──────────────────────────────────────────────
#  ИНТЕРФЕЙС
# ──────────────────────────────────────────────
st.title("📐 Теория ОГЭ по математике")
st.caption("Выберите номер задания и навык, нажмите «Посмотреть»")

grouped, all_keys = load_data()

col1, col2 = st.columns([1, 2])

with col1:
    key_labels     = [f"Задание {k}" if isinstance(k, int) else str(k) for k in all_keys]
    selected_label = st.selectbox("Номер задания ОГЭ", key_labels, key="sel_task")
    selected_key   = all_keys[key_labels.index(selected_label)]

with col2:
    items_for_key: list[dict] = grouped.get(selected_key, [])
    skill_options  = [item["goal_title"] for item in items_for_key]
    selected_skill = st.selectbox(
        "Навык",
        skill_options if skill_options else ["—"],
        key="sel_skill",
    )

if st.button("👁 Посмотреть", type="primary"):
    item = next((i for i in items_for_key if i["goal_title"] == selected_skill), None)
    if item and item.get("content"):
        st.session_state["_rendered"] = {
            "title":   selected_skill,
            "matched": item.get("_matched_skill"),
            "content": item["content"],
            "oge_num": item.get("_oge_num"),
        }
    else:
        st.session_state["_rendered"] = None
        st.warning("Нет содержимого для выбранного навыка.")

rendered = st.session_state.get("_rendered")
if rendered:
    st.divider()
    st.subheader(rendered["title"])

    matched = rendered.get("matched")
    if matched and matched != rendered["title"]:
        st.caption(f"Сопоставлен с навыком: «{matched}»")

    # На облаке srcdoc-iframe работает через HTTPS-origin → TikZJax грузится нормально
    html = make_full_html(rendered["content"], rendered["title"])
    components.html(html, height=960, scrolling=True)

    st.markdown("---")
    export_text = content_to_export_text(rendered["content"], rendered["title"])
    oge_num     = rendered.get("oge_num") or "без_номера"
    filename    = f"Задание_{oge_num}_{safe_filename(rendered['title'])}.txt"

    st.download_button(
        label="⬇️ Выгрузить текст",
        data=export_text.encode("utf-8"),
        file_name=filename,
        mime="text/plain; charset=utf-8",
    )
