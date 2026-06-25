from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

class Snippet(BaseModel):
    id: int
    name: str
    text: str
    preset_idx: int = 0
    font_size: Optional[int] = None

class Category(BaseModel):
    name: str
    order_idx: int
    snippets: List[Snippet] = Field(default_factory=list)

class Settings(BaseModel):
    theme: str = "Default"
    font_family: str = "Verdana"
    font_size: int = 11
    ui_scale: str = "1.0"
    window_locked: str = "0"
    sidebar_right: str = "0"
    hide_extra: int = 0
    act_like_normal_window: str = "0"
    show_shortkeys: int = 1
    summon_hotkey: str = "Ctrl+Shift+P"
    pie_summon_hotkey: str = "Alt+E"
    kill_hotkey: str = "Ctrl+Alt+Shift+Q"
    cats_order: List[str] = Field(default_factory=lambda: ["Code", "Text", "Misc"])
