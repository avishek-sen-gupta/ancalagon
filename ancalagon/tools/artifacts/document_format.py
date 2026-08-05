# The output formats a document may be converted to.
import enum


class DocumentFormat(enum.StrEnum):
    MARKDOWN = "markdown"
    PLAIN = "plain"
    JSON = "json"
    HTML = "html"
