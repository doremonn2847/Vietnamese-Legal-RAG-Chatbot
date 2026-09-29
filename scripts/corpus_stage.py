"""Employment-scope staging and article-first parsing for the pinned snapshot."""
import hashlib
import html
import re
import uuid
from html.parser import HTMLParser


EMPLOYMENT_TERMS = (
    "bộ luật lao động", "quan hệ lao động", "người lao động", "hợp đồng lao động", "hợp đồng thử việc",
    "chấm dứt hợp đồng", "thử việc", "tiền lương", "thời giờ làm việc",
    "làm thêm giờ", "nghỉ hằng năm", "nghỉ hàng năm", "nghỉ phép", "nghỉ lễ",
    "kỷ luật lao động", "trợ cấp thôi việc", "tạm hoãn hợp đồng",
)
ARTICLE_RE = re.compile(r"\bĐiều\s+\d+[A-Za-zÀ-ỹ0-9/-]*", re.I)
CHAPTER_RE = re.compile(r"\bChương\s+[IVXLCDM0-9]+\b", re.I)
SECTION_RE = re.compile(r"\bMục\s+[IVXLCDM0-9]+\b", re.I)
TAG_RE = re.compile(r"<[^>]*>", re.S)
IGNORED_RE = re.compile(r"<!--.*?-->|<(head|script|style|title)\b[^>]*>.*?</\1\s*>", re.S | re.I)
HEADING_RE = re.compile(r"^\s*(?:[-–—]\s*)?(Điều\s+\d+[A-Za-zÀ-ỹ0-9/-]*)(?=\s*(?:[.:–—-]|$)|\s+(?=(?-i:[A-ZĐ])))", re.I)
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "th", "section", "article", "div"}
SEPARATOR_TAGS = BLOCK_TAGS | {"br", "hr", "tr", "ul", "ol", "table"}


def _visible(raw):
    return _canonical_with_map(raw or "")[0]


def _mask_ignored(raw):
    return IGNORED_RE.sub(lambda match: " " * len(match.group(0)), raw or "")


def _bounded_raw_slices(raw, max_chars):
    """Split canonical text at sentence/word boundaries with raw mapping."""
    remaining = raw
    while remaining:
        text, spans = _canonical_with_map(remaining)
        if len(text) <= max_chars:
            yield remaining
            return
        boundary = 0
        if not boundary:
            whitespace = [match.start() for match in re.finditer(r"\s+", text[:max_chars + 1])]
            boundary = whitespace[-1] if whitespace else max_chars
        boundary = max(1, boundary)
        raw_cut = spans[boundary - 1][1]
        while raw_cut > 1 and len(_visible(remaining[:raw_cut])) > max_chars:
            boundary -= 1
            raw_cut = spans[boundary - 1][1]
        yield remaining[:raw_cut]
        remaining = remaining[raw_cut:]


def _canonical_with_map(raw):
    """Return canonical visible text and source spans for each canonical character."""
    chars, spans, pending_span, index = [], [], None, 0

    def append_space(span):
        if chars and chars[-1] != " ":
            chars.append(" ")
            spans.append(span)

    while index < len(raw):
        if raw[index] == "<":
            ignored = IGNORED_RE.match(raw, index)
            if ignored:
                index = ignored.end()
                continue
            end = raw.find(">", index + 1)
            if end < 0:
                end = len(raw) - 1
            tag = re.match(r"</?\s*([A-Za-z][\w:-]*)", raw[index:end + 1])
            if chars and tag and tag.group(1).lower() in SEPARATOR_TAGS:
                pending_span = (index, end + 1)
            index = end + 1
            continue
        if raw[index] == "&":
            end = raw.find(";", index + 1)
            if end >= 0:
                decoded = html.unescape(raw[index:end + 1])
                index_end = end + 1
            else:
                decoded, index_end = raw[index], index + 1
        else:
            decoded, index_end = raw[index], index + 1
        for char in decoded:
            if char.isspace():
                append_space((index, index_end))
            else:
                if pending_span is not None:
                    append_space(pending_span)
                    pending_span = None
                chars.append(char)
                spans.append((index, index_end))
        index = index_end
    while chars and chars[-1] == " ":
        chars.pop(); spans.pop()
    return "".join(chars), spans


def is_employment_candidate(row):
    return bool(employment_reasons(row))


def employment_reasons(row):
    title = (row.get("title") or "").casefold()
    fields = " ".join((row.get(key) or "") for key in ("nganh", "linh_vuc")).casefold()
    reasons = [term for term in EMPLOYMENT_TERMS if term in title]
    if "hợp đồng" in title and "lao động" in (title + " " + fields):
        reasons.append("labor_context_for_contract")
    return sorted(set(reasons))


def collect_dependency_ids(seed_ids, edges):
    seeds = set(seed_ids)
    return seeds | {target for source, target in edges if source in seeds}


def _stable_id(*parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "vietnamese-legal-rag:" + ":".join(str(part) for part in parts)))


def _common_structure_path(paths):
    if not paths:
        return []
    common = list(paths[0])
    for path in paths[1:]:
        length = min(len(common), len(path))
        while common[:length] != path[:length]:
            length -= 1
        common = common[:length]
    return common


class _BlockParser(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=False)
        self.raw = raw
        self.line_offsets = [0]
        self.line_offsets.extend(index + 1 for index, char in enumerate(raw) if char == "\n")
        self.stack = []
        self.blocks = []
        self.layout_anomalies = []

    def _absolute_offset(self):
        line, column = self.getpos()
        return self.line_offsets[min(line - 1, len(self.line_offsets) - 1)] + column

    def handle_starttag(self, tag, attrs):
        if tag.lower() in BLOCK_TAGS:
            if self.stack:
                self.stack[-1]["has_child_block"] = True
            self.stack.append({"tag": tag.lower(), "start": self._absolute_offset(), "parts": [], "has_child_block": False, "has_direct_text": False})

    def handle_startendtag(self, tag, attrs):
        return

    def handle_endtag(self, tag):
        tag = tag.lower()
        if not self.stack or self.stack[-1]["tag"] != tag:
            return
        block = self.stack.pop()
        end = self.raw.find(">", self._absolute_offset())
        end = len(self.raw) if end < 0 else end + 1
        text = " ".join("".join(block["parts"]).split())
        if block["has_child_block"] and block["has_direct_text"]:
            self.layout_anomalies.append({"reason": "mixed_block_content", "source_start": block["start"], "source_end": end})
        if text and not block["has_child_block"]:
            self.blocks.append((block["start"], end, text))

    def handle_data(self, data):
        if self.stack:
            if data.strip():
                self.stack[-1]["has_direct_text"] = True
            self.stack[-1]["parts"].append(data)

    def handle_entityref(self, name):
        self.handle_data(html.unescape(f"&{name};"))

    def handle_charref(self, name):
        self.handle_data(html.unescape(f"&#{name};"))


def _segments(raw):
    masked = _mask_ignored(raw or "")
    parser = _BlockParser(masked)
    parser.feed(masked)
    parser.close()
    blocks = sorted(parser.blocks)
    if blocks:
        return blocks
    return [(match.start(1), match.end(1), " ".join(html.unescape(match.group(1)).split())) for match in re.finditer(r">([^<>]+)<", masked, re.S) if match.group(1).strip()]


def layout_anomalies(raw):
    masked = _mask_ignored(raw or "")
    parser = _BlockParser(masked)
    parser.feed(masked)
    parser.close()
    anomalies = list(parser.layout_anomalies)
    if parser.stack:
        anomalies.append({"reason": "unclosed_block", "source_start": parser.stack[-1]["start"], "source_end": len(masked)})
    return anomalies


def parse_articles(document_id, raw_html, max_chars=6000):
    raw_html = raw_html or ""
    segments = _segments(_mask_ignored(raw_html))
    starts = []
    chapter = section = None
    for start, end, text in segments:
        chapter_match = CHAPTER_RE.search(text)
        section_match = SECTION_RE.search(text)
        if chapter_match:
            chapter = chapter_match.group(0)
            section = None
        if section_match:
            section = section_match.group(0)
        article_match = HEADING_RE.match(text)
        if article_match:
            starts.append((start, chapter, section, article_match.group(1)))
    articles = []
    for index, (source_start, chapter, section, label) in enumerate(starts):
        source_end = starts[index + 1][0] if index + 1 < len(starts) else len(raw_html)
        source_html = raw_html[source_start:source_end]
        canonical_text = _visible(source_html)
        content_sha256 = hashlib.sha256(raw_html.encode("utf-8")).hexdigest()
        document_version_id = _stable_id(document_id, content_sha256)
        article_id = _stable_id(document_version_id, label, source_start)
        cross_references = sorted(set(ARTICLE_RE.findall(canonical_text)[1:]))
        hierarchy = [{"structure_path": [label], "source_start": source_start, "source_end": source_end}]
        current_clause = None
        for block_start, block_end, block_text in segments:
            if block_start < source_start or block_start >= source_end:
                continue
            clause = re.match(r"^\s*(\d+)\.\s+", block_text)
            point = re.match(r"^\s*([a-zđ])\)\s+", block_text, re.I)
            if clause:
                current_clause = f"khoản {clause.group(1)}"
                hierarchy.append({"structure_path": [label, current_clause], "source_start": block_start, "source_end": min(block_end, source_end)})
            elif point:
                path = [label] + ([current_clause] if current_clause else []) + [f"điểm {point.group(1).lower()})"]
                hierarchy.append({"structure_path": path, "source_start": block_start, "source_end": min(block_end, source_end)})
        article = {
            "article_id": article_id, "article_version_id": article_id, "document_id": document_id,
            "document_version_id": document_version_id, "content_sha256": content_sha256, "label": label,
            "chapter": chapter, "section": section, "canonical_text": canonical_text,
            "source_start": source_start, "source_end": source_end, "source_html": source_html,
            "cross_references": cross_references, "hierarchy": hierarchy, "children": [],
            "validity": "unverified", "employment_scope": "provisional",
        }
        if len(canonical_text) > max_chars:
            article_blocks = [block for block in segments if source_start <= block[0] < source_end]
            chunks = []
            cursor = source_start
            current_start = source_start
            current_path = [label]
            current_paths = [[label]]
            current_clause = None

            def add_region(region_start, region_end, path, covered_paths):
                part_cursor = region_start
                for part in _bounded_raw_slices(raw_html[region_start:region_end], max_chars):
                    part_end = part_cursor + len(part)
                    chunks.append((part_cursor, part_end, path, list(covered_paths)))
                    part_cursor = part_end

            for block_start, block_end, block_text in article_blocks:
                if block_end > source_end:
                    block_end = source_end
                block_path = [label]
                clause_match = re.match(r"^\s*(\d+)\.\s+", block_text)
                point_match = re.match(r"^\s*([a-zđ])\)\s+", block_text, re.I)
                if clause_match:
                    current_clause = f"khoản {clause_match.group(1)}"
                if point_match and current_clause:
                    block_path += [current_clause, f"điểm {point_match.group(1).lower()})"]
                elif current_clause:
                    block_path += [current_clause]
                elif point_match:
                    block_path += [f"điểm {point_match.group(1).lower()})"]
                raw_block = raw_html[block_start:block_end]
                block_text_len = len(_visible(raw_block))
                proposed = _visible(raw_html[current_start:block_end])
                if len(proposed) > max_chars and current_start < block_start:
                    add_region(current_start, block_start, current_path, current_paths)
                    current_start = block_start
                if block_text_len > max_chars:
                    if current_start < block_start:
                        add_region(current_start, block_start, current_path, current_paths)
                    part_cursor = block_start
                    for part in _bounded_raw_slices(raw_block, max_chars):
                        part_end = part_cursor + len(part)
                        chunks.append((part_cursor, part_end, block_path, [block_path]))
                        part_cursor = part_end
                    current_start = block_end
                    current_path = block_path
                    current_paths = [block_path]
                else:
                    if current_start == block_start:
                        current_path = block_path
                        current_paths = [block_path]
                    elif block_path not in current_paths:
                        current_paths.append(block_path)
                cursor = block_end
            if current_start < source_end:
                add_region(current_start, source_end, current_path, current_paths)
            for child_index, (child_start, child_end, path, covered_paths) in enumerate(chunks):
                child_html = raw_html[child_start:child_end]
                child_text = _visible(child_html)
                path = _common_structure_path(covered_paths) or [label]
                article["children"].append({
                    "child_id": _stable_id(article_id, child_index), "parent_article_id": article_id,
                    "document_id": document_id, "label": path[-1] if len(path) > 1 else None,
                    "structure_path": path, "canonical_text": child_text,
                    "covered_structure_paths": covered_paths,
                    "source_start": child_start, "source_end": child_end, "source_html": child_html,
                })
        articles.append(article)
    return articles
