# Source for the contract written into any task whose caller named none of its own.
FREE_TEXT_MODULE = "import pydantic\n\n\nclass FreeText(pydantic.BaseModel):\n    text: str\n"
FREE_TEXT_FILE = "free_text.py"
