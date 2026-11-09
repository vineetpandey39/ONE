"""Publication requires a separate editorial decision bound to the final master."""

def editorial_ready(technical, editorial, master_sha256):
    return (technical.get('status') == 'technical_passed'
            and technical.get('master_sha256') == master_sha256
            and editorial.get('status') == 'passed'
            and editorial.get('master_sha256') == master_sha256
            and bool(editorial.get('reviewer')))
