"""紫桜のプレースホルダ立ち絵(表情差分SVG)を生成する。

本番のキャラクター画像ができたら frontend/public/character/ に同名で
置き換えるだけでよい(拡張子を変える場合は CharacterView.tsx を修正)。

    python assets/character/generate_placeholders.py
"""

from __future__ import annotations

import math
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[2] / "frontend" / "public" / "character"

HAIR_BACK = "#6a4a9c"
HAIR_FRONT = "#8a63c9"
HAIR_SHINE = "#b79ae0"
OUTLINE = "#3a2b52"
SKIN = "#ffe8da"
EYE = "#4a2f72"
MOUTH = "#c9556f"
SAKURA = "#f7b6d2"
SWEAT = "#aee3ff"

L, R = (103, 160), (157, 160)  # 目の基準位置


def open_eye(cx: int, cy: int, pupil_dx: int = 0, pupil_dy: int = 0, ry: int = 13) -> str:
    return f"""
    <path d="M{cx - 13},{cy - 12} Q{cx},{cy - 19} {cx + 13},{cy - 12}"
          stroke="{OUTLINE}" stroke-width="3.4" fill="none" stroke-linecap="round"/>
    <ellipse cx="{cx + pupil_dx}" cy="{cy + pupil_dy}" rx="10" ry="{ry}" fill="{EYE}"/>
    <circle cx="{cx + pupil_dx - 3}" cy="{cy + pupil_dy - 4}" r="3.4" fill="#fff" opacity="0.95"/>
    <circle cx="{cx + pupil_dx + 3}" cy="{cy + pupil_dy + 4}" r="1.7" fill="#fff" opacity="0.6"/>
    """


def happy_eye(cx: int, cy: int) -> str:
    return f"""
    <path d="M{cx - 11},{cy} Q{cx},{cy - 13} {cx + 11},{cy}"
          stroke="{OUTLINE}" stroke-width="4.2" fill="none" stroke-linecap="round"/>
    """


def half_eye(cx: int, cy: int, pupil_dx: int = 0) -> str:
    return f"""
    <path d="M{cx - 12},{cy - 8} Q{cx},{cy - 13} {cx + 12},{cy - 8}"
          stroke="{OUTLINE}" stroke-width="3.4" fill="none" stroke-linecap="round"/>
    <ellipse cx="{cx + pupil_dx}" cy="{cy + 2}" rx="9" ry="7" fill="{EYE}"/>
    <circle cx="{cx + pupil_dx - 3}" cy="{cy}" r="2.4" fill="#fff" opacity="0.9"/>
    """


def wide_eye(cx: int, cy: int) -> str:
    return f"""
    <path d="M{cx - 13},{cy - 13} Q{cx},{cy - 20} {cx + 13},{cy - 13}"
          stroke="{OUTLINE}" stroke-width="3.4" fill="none" stroke-linecap="round"/>
    <circle cx="{cx}" cy="{cy}" r="11" fill="{EYE}"/>
    <circle cx="{cx}" cy="{cy}" r="4.5" fill="#2a1b45"/>
    <circle cx="{cx - 4}" cy="{cy - 4}" r="3.2" fill="#fff" opacity="0.95"/>
    """


def brows(kind: str) -> str:
    (lx, ly), (rx, ry) = L, R
    y = ly - 27
    if kind == "normal":
        return f"""
        <path d="M{lx - 11},{y} Q{lx},{y - 4} {lx + 11},{y}" stroke="{OUTLINE}" stroke-width="2.6" fill="none" stroke-linecap="round"/>
        <path d="M{rx - 11},{y} Q{rx},{y - 4} {rx + 11},{y}" stroke="{OUTLINE}" stroke-width="2.6" fill="none" stroke-linecap="round"/>
        """
    if kind == "raised":
        y -= 5
        return f"""
        <path d="M{lx - 11},{y} Q{lx},{y - 6} {lx + 11},{y}" stroke="{OUTLINE}" stroke-width="2.6" fill="none" stroke-linecap="round"/>
        <path d="M{rx - 11},{y} Q{rx},{y - 6} {rx + 11},{y}" stroke="{OUTLINE}" stroke-width="2.6" fill="none" stroke-linecap="round"/>
        """
    # sad / troubled: 眉尻下がり(内側が上)
    return f"""
    <path d="M{lx - 11},{y + 2} Q{lx + 2},{y - 3} {lx + 11},{y - 5}" stroke="{OUTLINE}" stroke-width="2.6" fill="none" stroke-linecap="round"/>
    <path d="M{rx - 11},{y - 5} Q{rx - 2},{y - 3} {rx + 11},{y + 2}" stroke="{OUTLINE}" stroke-width="2.6" fill="none" stroke-linecap="round"/>
    """


def sakura_flower(cx: int, cy: int, r: float = 8.5) -> str:
    petals = []
    for i in range(5):
        a = math.radians(90 + i * 72)
        petals.append(
            f'<circle cx="{cx + r * math.cos(a):.1f}" cy="{cy - r * math.sin(a):.1f}" r="6" fill="{SAKURA}"/>'
        )
    return "\n".join(petals) + f'\n<circle cx="{cx}" cy="{cy}" r="3.2" fill="#ffd97a"/>'


MOUTHS = {
    "smile": f'<path d="M122,193 Q130,200 138,193" stroke="{MOUTH}" stroke-width="3" fill="none" stroke-linecap="round"/>',
    "open_smile": f'<path d="M117,190 Q130,208 143,190 Q130,197 117,190 Z" fill="{MOUTH}"/>',
    "frown": f'<path d="M121,198 Q130,191 139,198" stroke="{MOUTH}" stroke-width="3" fill="none" stroke-linecap="round"/>',
    "small_o": f'<ellipse cx="130" cy="196" rx="6" ry="7.5" fill="{MOUTH}"/>',
    "wavy": f'<path d="M118,195 q6,-7 12,0 q6,7 12,0" stroke="{MOUTH}" stroke-width="3" fill="none" stroke-linecap="round"/>',
    "tiny": f'<path d="M125,194 Q130,197 135,194" stroke="{MOUTH}" stroke-width="2.6" fill="none" stroke-linecap="round"/>',
    "flat": f'<path d="M124,195 L136,195" stroke="{MOUTH}" stroke-width="3" fill="none" stroke-linecap="round"/>',
}

EXTRAS = {
    "tear": f'<path d="M86,176 q-7,12 0,17 q7,-5 0,-17 Z" fill="{SWEAT}" opacity="0.9"/>',
    "sweat": f'<path d="M197,118 q9,15 0,21 q-9,-6 0,-21 Z" fill="{SWEAT}" opacity="0.9"/>',
    "sparkles": """
    <path d="M206,62 l3,8 8,3 -8,3 -3,8 -3,-8 -8,-3 8,-3 Z" fill="#ffe9a8"/>
    <path d="M52,84 l2.4,6.4 6.4,2.4 -6.4,2.4 -2.4,6.4 -2.4,-6.4 -6.4,-2.4 6.4,-2.4 Z" fill="#ffe9a8"/>
    """,
    "thought_dots": """
    <circle cx="196" cy="58" r="4" fill="#cbb6ef" opacity="0.85"/>
    <circle cx="208" cy="44" r="5.5" fill="#cbb6ef" opacity="0.85"/>
    <circle cx="222" cy="27" r="7" fill="#cbb6ef" opacity="0.85"/>
    """,
}

# 表情ごとの構成(docs/05 §1.3 の感情タグと1:1対応)
EMOTIONS: dict[str, dict] = {
    "normal": {"eyes": open_eye(*L) + open_eye(*R), "brows": brows("normal"), "mouth": MOUTHS["smile"], "blush": 0.35},
    "joy": {"eyes": happy_eye(*L) + happy_eye(*R), "brows": brows("normal"), "mouth": MOUTHS["open_smile"], "blush": 0.75},
    "sad": {"eyes": open_eye(*L, pupil_dy=2, ry=12) + open_eye(*R, pupil_dy=2, ry=12), "brows": brows("sad"), "mouth": MOUTHS["frown"], "blush": 0.3, "extra": EXTRAS["tear"]},
    "surprised": {"eyes": wide_eye(*L) + wide_eye(*R), "brows": brows("raised"), "mouth": MOUTHS["small_o"], "blush": 0.4, "extra": EXTRAS["sparkles"]},
    "troubled": {"eyes": open_eye(*L, pupil_dy=1) + open_eye(*R, pupil_dy=1), "brows": brows("sad"), "mouth": MOUTHS["wavy"], "blush": 0.45, "extra": EXTRAS["sweat"]},
    "shy": {"eyes": half_eye(*L, pupil_dx=4) + half_eye(*R, pupil_dx=4), "brows": brows("sad"), "mouth": MOUTHS["tiny"], "blush": 1.0},
    "thinking": {"eyes": open_eye(*L, pupil_dx=3, pupil_dy=-4) + open_eye(*R, pupil_dx=3, pupil_dy=-4), "brows": brows("raised"), "mouth": MOUTHS["flat"], "blush": 0.3, "extra": EXTRAS["thought_dots"]},
}


def render(spec: dict) -> str:
    blush_opacity = spec.get("blush", 0.35)
    extra = spec.get("extra", "")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 340">
  <!-- 後ろ髪 -->
  <ellipse cx="130" cy="128" rx="86" ry="92" fill="{HAIR_BACK}"/>
  <path d="M46,140 C34,220 44,292 66,324 C80,300 74,220 74,158 Z" fill="{HAIR_BACK}"/>
  <path d="M214,140 C226,220 216,292 194,324 C180,300 186,220 186,158 Z" fill="{HAIR_BACK}"/>
  <!-- 首・体 -->
  <rect x="119" y="198" width="22" height="60" rx="9" fill="{SKIN}"/>
  <path d="M68,340 C68,278 92,250 130,250 C168,250 192,278 192,340 Z" fill="#38294f"/>
  <path d="M100,256 L130,290 L160,256" stroke="{SAKURA}" stroke-width="6" fill="none" stroke-linejoin="round"/>
  <circle cx="130" cy="292" r="6" fill="{SAKURA}"/>
  <!-- 顔 -->
  <ellipse cx="130" cy="150" rx="60" ry="56" fill="{SKIN}"/>
  <!-- 前髪 -->
  <path d="M62,150 C58,84 88,56 130,56 C172,56 202,84 198,150
           C186,126 176,122 166,134 C160,114 148,110 138,126
           C128,108 112,110 104,130 C92,118 74,126 62,150 Z" fill="{HAIR_FRONT}"/>
  <path d="M64,138 C56,190 60,222 72,240 C82,220 80,178 80,148 Z" fill="{HAIR_FRONT}"/>
  <path d="M196,138 C204,190 200,222 188,240 C178,220 180,178 180,148 Z" fill="{HAIR_FRONT}"/>
  <path d="M126,56 C116,36 138,26 146,38 C136,36 132,44 134,54 Z" fill="{HAIR_FRONT}"/>
  <path d="M86,82 Q112,62 152,66" stroke="{HAIR_SHINE}" stroke-width="5" fill="none" opacity="0.55" stroke-linecap="round"/>
  <!-- 桜の髪飾り -->
  {sakura_flower(180, 88)}
  <!-- 頬紅 -->
  <ellipse cx="97" cy="182" rx="11" ry="6" fill="{SAKURA}" opacity="{blush_opacity}"/>
  <ellipse cx="163" cy="182" rx="11" ry="6" fill="{SAKURA}" opacity="{blush_opacity}"/>
  <!-- 表情 -->
  {spec["brows"]}
  {spec["eyes"]}
  {spec["mouth"]}
  {extra}
</svg>
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, spec in EMOTIONS.items():
        (OUT_DIR / f"{name}.svg").write_text(render(spec), encoding="utf-8")
        print(f"wrote {OUT_DIR / f'{name}.svg'}")


if __name__ == "__main__":
    main()
