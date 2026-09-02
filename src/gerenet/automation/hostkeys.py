def normalize_fingerprint(fingerprint: str) -> str:
    """Canonicaliza 'SHA256:AbC' / '  sha256:abc  ' para 'sha256:AbC'.

    Normaliza só o rótulo do esquema ('sha256:'). O corpo base64 preserva
    maiúsculas/minúsculas — ele é dado do hash e não pode ser alterado.
    """
    fp = fingerprint.strip()
    if ":" in fp:
        esquema, valor = fp.split(":", 1)
        return f"{esquema.strip().lower()}:{valor.strip()}"
    return fp
