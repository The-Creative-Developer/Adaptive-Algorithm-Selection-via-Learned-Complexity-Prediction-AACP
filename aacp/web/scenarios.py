"""Ready-made custom problems for demonstrations (all data is invented)."""

from __future__ import annotations


def _build(names, edge_text):
    idx = {n: i for i, n in enumerate(names)}
    edges = []
    for pair in edge_text.split(","):
        pair = pair.strip()
        # names may contain '-', so try every '-' until both halves are known vertices
        cuts = [i for i, ch in enumerate(pair) if ch == "-"]
        for i in cuts:
            a, b = pair[:i], pair[i + 1:]
            if a in idx and b in idx:
                edges.append([idx[a], idx[b]])
                break
        else:
            raise ValueError(f"cannot split edge {pair!r}")
    return idx, edges


def network_monitoring():
    names = ["core", "fw", "sw-1", "sw-2", "sw-3", "sw-4", "web", "db", "mail", "files",
             "backup", "wifi", "printer", "lab-1", "lab-2", "lab-3", "hr-pc", "fin-pc", "vpn", "dns"]
    _, edges = _build(names, "core-fw,core-sw-1,core-sw-2,core-sw-3,core-sw-4,fw-vpn,fw-dns,"
                      "sw-1-web,sw-1-db,sw-1-mail,sw-2-files,sw-2-backup,sw-2-db,sw-3-wifi,sw-3-printer,"
                      "sw-3-hr-pc,sw-3-fin-pc,sw-4-lab-1,sw-4-lab-2,sw-4-lab-3,web-db,db-backup,"
                      "files-backup,lab-1-lab-2,lab-2-lab-3,vpn-mail,dns-web,dns-mail,wifi-printer")
    return {"id": "monitoring", "title": "Network monitoring", "kind": "vertex_cover",
            "story": "Place packet monitors on as few devices as possible so that every network link "
                     "is observed by a monitor at one of its ends.",
            "labels": names, "edges": edges, "weights": None, "require": [], "forbid": []}


def patch_plan():
    names = ["dc-01", "web-01", "web-02", "api-gw", "db-main", "db-replica", "cache", "queue",
             "erp-legacy", "scada-hmi", "jump-host", "dev-laptop", "ci-runner", "backup-srv",
             "mail-gw", "vpn-gw"]
    hours = [6, 2, 2, 3, 8, 5, 1, 2, 20, 12, 2, 1, 3, 4, 2, 3]
    idx, edges = _build(names, "vpn-gw-jump-host,jump-host-dc-01,jump-host-db-main,web-01-api-gw,"
                        "web-02-api-gw,api-gw-db-main,api-gw-cache,api-gw-queue,queue-erp-legacy,"
                        "erp-legacy-db-main,erp-legacy-scada-hmi,scada-hmi-jump-host,dev-laptop-ci-runner,"
                        "ci-runner-api-gw,ci-runner-dc-01,db-main-db-replica,db-replica-backup-srv,"
                        "backup-srv-dc-01,mail-gw-dc-01,mail-gw-web-01,dev-laptop-vpn-gw,web-01-web-02")
    return {"id": "patching", "title": "Security patch plan", "kind": "vertex_cover",
            "story": "Edges are lateral-movement paths between hosts. Patch hosts so every path has a "
                     "patched end, minimising total patch hours. The legacy ERP cannot be patched; "
                     "policy requires patching the domain controller.",
            "labels": names, "edges": edges, "weights": hours,
            "require": [idx["dc-01"]], "forbid": [idx["erp-legacy"]]}


def exam_slot():
    names = ["DAA", "OS", "DBMS", "CN", "ML", "AI", "TOC", "SE", "Maths-III", "Compilers",
             "Graphics", "Crypto", "Cloud", "IoT", "HCI", "Ethics"]
    _, edges = _build(names, "DAA-OS,DAA-TOC,DAA-Maths-III,DAA-ML,OS-DBMS,OS-CN,OS-Compilers,DBMS-SE,"
                      "DBMS-Cloud,CN-IoT,CN-Crypto,CN-Cloud,ML-AI,ML-Maths-III,AI-HCI,TOC-Compilers,"
                      "TOC-Crypto,SE-HCI,SE-Ethics,Graphics-HCI,Graphics-Maths-III,Crypto-Maths-III,"
                      "Cloud-IoT,IoT-Ethics,AI-Ethics")
    return {"id": "exams", "title": "Exam timetable slot", "kind": "independent_set",
            "story": "Two exams conflict when a student takes both. Pick the largest set of exams that "
                     "can share one time slot.",
            "labels": names, "edges": edges, "weights": None, "require": [], "forbid": []}


def team_builder():
    names = ["you", "Asha", "Ben", "Chen", "Dev", "Elif", "Farid", "Gita", "Hugo", "Ines",
             "Jun", "Kofi", "Lena", "Mira", "Nils", "Omar"]
    years = [3, 7, 4, 9, 2, 6, 5, 8, 3, 4, 6, 2, 5, 7, 3, 4]
    idx, edges = _build(names, "you-Asha,you-Chen,you-Gita,you-Mira,you-Dev,you-Lena,Asha-Chen,Asha-Gita,"
                        "Asha-Mira,Chen-Gita,Chen-Mira,Gita-Mira,Asha-Elif,Chen-Elif,Elif-Farid,"
                        "Farid-Hugo,Hugo-Ines,Ines-Jun,Jun-Kofi,Kofi-Lena,Lena-Mira,Dev-Lena,Dev-Nils,"
                        "Nils-Omar,Omar-Ben,Ben-Hugo,Ben-Ines,Hugo-Jun,Farid-Elif,Gita-Lena,Elif-Gita")
    return {"id": "team", "title": "Team builder", "kind": "clique",
            "story": "An edge means two people have worked together. Find the most experienced team "
                     "(vertex value = years of experience) in which everyone has worked with everyone, "
                     "and that includes you.",
            "labels": names, "edges": edges, "weights": years, "require": [idx["you"]], "forbid": []}


SCENARIOS = [network_monitoring(), patch_plan(), exam_slot(), team_builder()]
