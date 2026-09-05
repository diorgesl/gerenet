def normalize_fingerprint(fingerprint: str) -> str:
    """Canonicaliza 'SHA256:AbC=' / '  sha256:abc  ' para 'sha256:AbC' (sem padding).

    O esquema vira minúsculo; o corpo base64 preserva maiúsculas/minúsculas —
    ele é dado do hash e não pode ser alterado. Só o padding '=' final é removido:
    'ssh-keygen -lf' imprime sem padding e o cálculo sha256 do lado servidor
    adiciona; a mesma chave precisa canonicalizar igual nos dois lados.
    """
    fp = fingerprint.strip().rstrip("=")
    if ":" in fp:
        esquema, valor = fp.split(":", 1)
        return f"{esquema.strip().lower()}:{valor.strip()}"
    return fp
