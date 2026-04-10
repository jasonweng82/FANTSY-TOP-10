"""
image_generator.py
產生 Yahoo Fantasy MLB 圖卡（ESPN 深色風格）
"""

from PIL import Image, ImageDraw, ImageFont
import io

FONT_REG  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
EN_REG    = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
EN_BOLD   = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

BG_DARK   = "#0f1923"
BG_ROW1   = "#1a2535"
BG_ROW2   = "#131f2e"
BG_BADGE  = "#1d3a5f"
BLUE_BAR  = "#2563eb"
BLUE_LT   = "#60a5fa"
PURPLE    = "#c084fc"
GOLD      = "#f59e0b"
GREEN     = "#22c55e"
RED       = "#ef4444"
NEW_BLUE  = "#3b82f6"
WHITE     = "#ffffff"
GRAY      = "#94a3b8"
DK_GRAY   = "#64748b"
DIVIDER   = "#1e2d3d"
FOOTER_C  = "#374151"

W        = 840
ROW_H    = 90
PAD_X    = 30
Y_HEADER = 148

def _fonts(sizes):
    out = {}
    for name, path, size in sizes:
        try:
            out[name] = ImageFont.truetype(path, size)
        except Exception:
            out[name] = ImageFont.load_default()
    return out

def _std_fonts():
    return _fonts([
        ("title",  FONT_BOLD, 34), ("sub",    FONT_REG,  22),
        ("rank",   EN_BOLD,   30), ("name",   EN_BOLD,   26),
        ("detail", FONT_REG,  20), ("pos",    EN_BOLD,   20),
        ("score",  EN_BOLD,   28), ("footer", FONT_REG,  18),
    ])

def _canvas(n_rows):
    H   = Y_HEADER + n_rows * ROW_H + 70
    img = Image.new("RGB", (W, H), BG_DARK)
    return img, ImageDraw.Draw(img)

def _header(d, fonts, title, subtitle):
    d.rectangle([0, 0, W, 8], fill=BLUE_BAR)
    d.text((PAD_X, 26), title,    font=fonts["title"], fill=WHITE)
    d.text((PAD_X, 70), subtitle, font=fonts["sub"],   fill=DK_GRAY)
    d.line([(PAD_X, 108), (W-PAD_X, 108)], fill=DIVIDER, width=2)
    for x, label in [(PAD_X, "#"), (80, "PLAYER"), (520, "POS"), (630, "PTS"), (755, "TREND")]:
        d.text((x, 118), label, font=fonts["detail"], fill=DK_GRAY)

def _row(d, fonts, rank, name, team, pos, score, trend, tcol, bar_col):
    y  = Y_HEADER + (rank - 1) * ROW_H
    bg = BG_ROW1 if rank == 1 else BG_ROW2
    d.rounded_rectangle([20, y, W-20, y+ROW_H-6], radius=8, fill=bg)
    d.rounded_rectangle([20, y, 27,   y+ROW_H-6], radius=4, fill=bar_col)
    d.text((38, y+22), str(rank),             font=fonts["rank"],   fill=GOLD if rank==1 else GRAY)
    d.text((80, y+10), (name or "")[:22],     font=fonts["name"],   fill=WHITE)
    d.text((80, y+48), f"{team}  ·  {pos}",   font=fonts["detail"], fill=DK_GRAY)
    d.rounded_rectangle([508, y+20, 598, y+54], radius=4, fill=BG_BADGE)
    ps   = (pos or "??")[:4]
    bbox = d.textbbox((0, 0), ps, font=fonts["pos"])
    pw   = bbox[2] - bbox[0]
    pcol = PURPLE if pos in ("SP","RP","P","SP,RP") else BLUE_LT
    d.text((553 - pw//2, y+28), ps,        font=fonts["pos"],   fill=pcol)
    d.text((618, y+20),         f"{score:.1f}", font=fonts["score"], fill=WHITE)
    d.text((755, y+20),         trend,     font=fonts["score"], fill=tcol)

def _footer(d, fonts, n_rows, label="Yahoo Fantasy MLB Bot"):
    y = Y_HEADER + n_rows * ROW_H + 8
    d.line([(PAD_X, y), (W-PAD_X, y)], fill=DIVIDER, width=1)
    d.text((PAD_X,   y+12), label,        font=fonts["footer"], fill=FOOTER_C)
    d.text((W-PAD_X, y+12), "每日自動更新", font=fonts["footer"], fill=FOOTER_C, anchor="ra")

def _to_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()

def _bar(pos):
    return PURPLE if pos in ("SP","RP","P","SP,RP") else BLUE_LT

def _trend(prev_ranks, name, i):
    prev = prev_ranks.get(name)
    if prev is None:  return "NEW", NEW_BLUE
    diff = prev - i
    if diff > 0:      return f"▲{diff}", GREEN
    if diff < 0:      return f"▼{abs(diff)}", RED
    return "–", GRAY


def generate_season_top10(players, prev_ranks, today_str) -> bytes:
    fonts = _std_fonts()
    img, d = _canvas(len(players))
    _header(d, fonts, "本季累積得分 TOP 10", f"{today_str}  ·  Yahoo Fantasy MLB")
    for i, p in enumerate(players, 1):
        tr, tc = _trend(prev_ranks, p["name"], i)
        _row(d, fonts, i, p["name"], p["team"], p["position"], p["score"], tr, tc, _bar(p["position"]))
    _footer(d, fonts, len(players))
    return _to_bytes(img)


def generate_today_top10(players, today_str) -> bytes:
    fonts = _std_fonts()
    img, d = _canvas(len(players))
    _header(d, fonts, "今日得分 TOP 10", f"{today_str}  ·  Yahoo Fantasy MLB")
    for i, p in enumerate(players, 1):
        sc = p["score"]
        tr = f"+{sc:.1f}" if sc >= 0 else f"{sc:.1f}"
        tc = GREEN if sc > 0 else (RED if sc < 0 else GRAY)
        _row(d, fonts, i, p["name"], p["team"], p["position"], sc, tr, tc, _bar(p["position"]))
    _footer(d, fonts, len(players), "今日得分排行")
    return _to_bytes(img)


def generate_today_bottom5(players, today_str) -> bytes:
    fonts = _std_fonts()
    img, d = _canvas(len(players))
    _header(d, fonts, "今日得分 BOTTOM 5", f"{today_str}  ·  Yahoo Fantasy MLB")
    for i, p in enumerate(players, 1):
        sc = p["score"]
        _row(d, fonts, i, p["name"], p["team"], p["position"], sc, f"{sc:.1f}", RED, _bar(p["position"]))
    _footer(d, fonts, len(players), "今日得分墊底")
    return _to_bytes(img)


def generate_free_agent_top5(players, today_str) -> bytes:
    fonts = _std_fonts()
    img, d = _canvas(len(players))
    _header(d, fonts, "本季 Free Agent TOP 5", f"{today_str}  ·  強烈推薦撿人")
    for i, p in enumerate(players, 1):
        _row(d, fonts, i, p["name"], p["team"], p["position"], p["score"], "FA", NEW_BLUE, _bar(p["position"]))
    _footer(d, fonts, len(players), "Free Agent 推薦")
    return _to_bytes(img)


def generate_weekly_report(players, week_label) -> bytes:
    fonts = _std_fonts()
    img, d = _canvas(len(players))
    _header(d, fonts, "本週得分 TOP 10", f"{week_label}  ·  Yahoo Fantasy MLB 週報")
    for i, p in enumerate(players, 1):
        _row(d, fonts, i, p["name"], p["team"], p["position"], p["score"], f"{p['score']:.1f}", BLUE_LT, _bar(p["position"]))
    _footer(d, fonts, len(players), "每週一自動發送")
    return _to_bytes(img)
