"""objectIdの採番。実行のたびに1から振り直す(種別ごと)。"""

BASE_URL = "http://localhost:3000"

# 種別(URLの種別部分)
KINDS = ("nfds", "fres", "tpes", "tls", "pPorts", "pds", "pls", "pStructs")

# LRSpec/PRSpecの固定objectId
LR_SPEC_FRE = BASE_URL + "/lrSpecs/spec_00000001"
LR_SPEC_TPE = BASE_URL + "/lrSpecs/spec_00000002"
LR_SPEC_NFD = BASE_URL + "/lrSpecs/spec_00000003"
LR_SPEC_TL = BASE_URL + "/lrSpecs/spec_00000004"
PR_SPEC_PD = BASE_URL + "/prSpecs/spec_00000005"
PR_SPEC_PLINK = BASE_URL + "/prSpecs/spec_00000006"
PR_SPEC_PPORT = BASE_URL + "/prSpecs/spec_00000007"
PR_SPEC_PSTRUCT = BASE_URL + "/prSpecs/spec_00000008"

# CE用PStructの固定objectId(採番しない)
CE_PSTRUCT_ID = BASE_URL + "/pStructs/system_00000000"


class ObjectIdManager(object):
    """種別ごとに1から採番する。"""

    def __init__(self):
        self._counters = {}

    def next_id(self, kind):
        if kind not in KINDS:
            raise ValueError("未知のobjectId種別です: %s" % kind)
        n = self._counters.get(kind, 0) + 1
        self._counters[kind] = n
        return "%s/%s/system_%08d" % (BASE_URL, kind, n)
