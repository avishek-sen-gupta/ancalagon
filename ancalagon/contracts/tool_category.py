# What kind of work a tool does, so nothing has to read its name to find out.
import enum


class ToolCategory(enum.Enum):
    FILES = "files"
    SEARCH = "search"
    PARSE = "parse"
    ARTIFACTS = "artifacts"
    CITE = "cite"
    COMPARE = "compare"
    HISTORY = "history"
    SURVEY = "survey"
    SHELL = "shell"
    WEB = "web"
    WATCH = "watch"
    TASKS = "tasks"
    DELEGATE = "delegate"
    SUBMIT = "submit"
    LIFECYCLE = "lifecycle"
