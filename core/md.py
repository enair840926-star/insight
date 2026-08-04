# -*- coding: utf-8 -*-
"""마크다운 → HTML (최소 구현)

LLM이 돌려주는 인사이트를 화면에 붙이려면 변환이 필요한데,
그것만 하려고 의존성을 늘리지 않는다. 실제로 쓰이는 문법만 지원한다:
제목 / 굵게 / 기울임 / 인라인코드 / 목록 / 표 / 인용 / 구분선 / 문단.
"""
import re

_ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}


def _esc(s):
    return "".join(_ESC.get(c, c) for c in s)


def _inline(s):
    """굵게·기울임·코드·링크. 이스케이프를 먼저 하고 태그를 넣는다."""
    s = _esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
               r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    return s


def _table(lines):
    """| a | b |  형식. 두 번째 줄이 구분선이면 표로 본다."""
    def cells(row):
        return [c.strip() for c in row.strip().strip("|").split("|")]

    head = cells(lines[0])
    body = [cells(r) for r in lines[2:]]
    th = "".join(f"<th>{_inline(c)}</th>" for c in head)
    rows = ""
    for r in body:
        # 열 수가 안 맞아도 깨지지 않게 맞춰준다
        r = (r + [""] * len(head))[:len(head)]
        rows += "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
    return (f'<div class="scroll"><table><thead><tr>{th}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div>")


def render(text):
    if not text:
        return ""
    lines = text.replace("\r\n", "\n").split("\n")
    out, i = [], 0

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()

        if not s:
            i += 1
            continue

        # 표: 헤더 + |---| 구분선
        if (s.startswith("|") and i + 1 < len(lines)
                and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip())):
            block = [lines[i], lines[i + 1]]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            out.append(_table(block))
            continue

        # 제목
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            # 카드 제목이 h2라 그 아래로 넣는다. LLM은 보통 ##를 주 섹션으로
            # 쓰므로 #·##를 같은 h3로 묶고, 그보다 깊은 것만 h4로 내린다.
            lvl = 3 if len(m.group(1)) <= 2 else 4
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue

        # 구분선
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            out.append("<hr>")
            i += 1
            continue

        # 인용
        if s.startswith(">"):
            block = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                block.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(f"<blockquote>{_inline(' '.join(block))}</blockquote>")
            continue

        # 목록 (번호·불릿)
        if re.match(r"^([-*+]|\d+\.)\s+", s):
            ordered = bool(re.match(r"^\d+\.", s))
            items = []
            while i < len(lines) and re.match(r"^([-*+]|\d+\.)\s+",
                                              lines[i].strip()):
                items.append(re.sub(r"^([-*+]|\d+\.)\s+", "", lines[i].strip()))
                i += 1
            tag = "ol" if ordered else "ul"
            body = "".join(f"<li>{_inline(x)}</li>" for x in items)
            out.append(f"<{tag}>{body}</{tag}>")
            continue

        # 문단 — 빈 줄까지 모은다
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^(#{1,4}\s|[-*+]\s|\d+\.\s|>|\||-{3,})", lines[i].strip()):
            para.append(lines[i].strip())
            i += 1
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")

    return "".join(out)
