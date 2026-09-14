"""五个栏目页面，各自独立。"""
from .workbench import WorkbenchPage
from .data import DataPage
from .preprocess import PreprocessPage
from .analysis import AnalysisPage
from .results import ResultsPage
from .settings import SettingsPage

__all__ = [
    "WorkbenchPage",
    "DataPage",
    "PreprocessPage",
    "AnalysisPage",
    "ResultsPage",
    "SettingsPage",
]
