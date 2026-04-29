import re

def split_sql_script(script: str) -> list[str]:
    if not script:
        return []

    parts = re.split(r'^\s*/\s*$', script, flags=re.MULTILINE)

    statements = []
    for part in parts:
        clean_part = part.strip()
        if not clean_part:
            continue

        content_only = re.sub(r'--.*$', '', clean_part, flags=re.MULTILINE)
        content_only = re.sub(r'/\*.*?\*/', '', content_only, flags=re.DOTALL).strip()

        if re.match(r'^(BEGIN|DECLARE)', content_only, re.IGNORECASE):
            statements.append(clean_part)
        else:
            sub_stmts = [s.strip() for s in clean_part.split(';') if s.strip()]
            statements.extend(sub_stmts)

    return statements

def clean_sql_statement(stmt: str) -> str:
    if not stmt:
        return ""

    cleaned = stmt.strip()
    cleaned = re.sub(r'[;/]\s*$', '', cleaned)
    return cleaned.strip()
