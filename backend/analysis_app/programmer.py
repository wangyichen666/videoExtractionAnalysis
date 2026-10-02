"""旧导入路径兼容层；新专家定义和引擎分别位于 expert_profiles/report_engine。"""
from .expert_profiles import PROFILE, PROMPT, LEGACY_PROMPT, SECTIONS, seed_experts
from .report_engine import source_chunks, bind_sources
