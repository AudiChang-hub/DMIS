import difflib


def _edits(base, changed):
    matcher = difflib.SequenceMatcher(a=base, b=changed, autojunk=False)
    return [
        (start, end, changed[new_start:new_end])
        for operation, start, end, new_start, new_end in matcher.get_opcodes()
        if operation != "equal"
    ]


def merge_text(base, server, client):
    """Three-way merge non-overlapping text edits; return None on ambiguity."""
    if client == server:
        return server
    if server == base:
        return client
    if client == base:
        return server

    server_edits = _edits(base, server)
    client_edits = _edits(base, client)
    combined = list(server_edits)

    for client_edit in client_edits:
        if client_edit in combined:
            continue
        client_start, client_end, _ = client_edit
        for server_start, server_end, _ in server_edits:
            same_insertion_point = (
                client_start == client_end
                and server_start == server_end
                and client_start == server_start
            )
            ranges_overlap = max(client_start, server_start) < min(
                client_end, server_end
            )
            insertion_inside_edit = (
                client_start == client_end
                and server_start <= client_start < server_end
            ) or (
                server_start == server_end
                and client_start <= server_start < client_end
            )
            if same_insertion_point or ranges_overlap or insertion_inside_edit:
                return None
        combined.append(client_edit)

    merged = base
    for start, end, replacement in sorted(
        combined, key=lambda item: (item[0], item[1]), reverse=True
    ):
        merged = merged[:start] + replacement + merged[end:]
    return merged
