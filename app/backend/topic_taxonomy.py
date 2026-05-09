from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TopicEntry:
    canonical: str
    aliases: tuple[str, ...]
    subtopics: tuple[str, ...] = ()
    related_terms: tuple[str, ...] = ()
    zh_aliases: tuple[str, ...] = ()
    domain: str | None = None

    def all_terms(self) -> list[str]:
        values: list[str] = [self.canonical, *self.aliases, *self.subtopics, *self.related_terms, *self.zh_aliases]
        deduped: list[str] = []
        seen: set[str] = set()
        for item in values:
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                deduped.append(item.strip())
        return deduped


TOPIC_TAXONOMY: tuple[TopicEntry, ...] = (
    TopicEntry(
        canonical="cryptography",
        aliases=("cryptographic", "crypto", "modern cryptography"),
        subtopics=(
            "encryption",
            "signature",
            "proof system",
            "secure computation",
            "zero-knowledge proof",
            "homomorphic encryption",
            "secure multiparty computation",
        ),
        related_terms=(
            "authenticated encryption",
            "public key encryption",
            "functional encryption",
            "threshold cryptography",
            "cryptographic protocol",
            "verifiable computation",
        ),
        zh_aliases=("密码学", "密码", "现代密码学", "密码协议"),
        domain="cryptography",
    ),
    TopicEntry(
        canonical="homomorphic encryption",
        aliases=("fhe", "fully homomorphic encryption", "leveled homomorphic encryption"),
        subtopics=("bootstrapping", "encrypted computation", "private inference"),
        related_terms=("ciphertext packing", "rlwe", "ckks", "bfv", "bgin", "encrypted machine learning"),
        zh_aliases=("同态加密", "全同态加密"),
        domain="cryptography",
    ),
    TopicEntry(
        canonical="zero-knowledge proofs",
        aliases=("zero knowledge proof", "zkp", "zk proof", "zero-knowledge"),
        subtopics=("zk-snark", "zk-stark", "succinct proof", "proof system"),
        related_terms=("verifiable computation", "argument system", "prover", "verifier", "polynomial commitment"),
        zh_aliases=("零知识证明", "零知识", "zk证明"),
        domain="cryptography",
    ),
    TopicEntry(
        canonical="secure multiparty computation",
        aliases=("multi-party computation", "mpc", "secure computation"),
        subtopics=("private set intersection", "garbled circuits", "secret sharing"),
        related_terms=("threshold computation", "privacy-preserving computation", "private aggregation"),
        zh_aliases=("安全多方计算", "多方安全计算", "多方计算", "安全计算"),
        domain="cryptography",
    ),
    TopicEntry(
        canonical="privacy-preserving computation",
        aliases=("privacy preserving computation", "private computation", "privacy-preserving systems"),
        subtopics=("private inference", "private training", "encrypted computation", "secure aggregation", "privacy-preserving machine learning"),
        related_terms=("private set intersection", "secure multiparty computation", "encrypted search"),
        zh_aliases=("隐私计算", "隐私保护计算", "隐私保护", "隐私保护系统"),
        domain="privacy",
    ),
    TopicEntry(
        canonical="privacy-preserving machine learning",
        aliases=("private learning", "privacy preserving machine learning", "private ml"),
        subtopics=("private inference", "private training", "federated learning security"),
        related_terms=("differential privacy", "encrypted inference", "secure aggregation", "privacy-preserving computation"),
        zh_aliases=("隐私保护机器学习", "隐私机器学习", "隐私保护学习"),
        domain="privacy",
    ),
    TopicEntry(
        canonical="anonymous credentials",
        aliases=("anonymous credential", "credential privacy", "selective disclosure"),
        subtopics=("group signature", "attribute-based credential"),
        related_terms=("unlinkability", "identity privacy", "privacy credential"),
        zh_aliases=("匿名凭证", "匿名认证", "选择性披露凭证"),
        domain="cryptography",
    ),
    TopicEntry(
        canonical="digital signatures",
        aliases=("digital signature", "signature scheme", "signatures"),
        subtopics=("aggregate signatures", "threshold signatures"),
        related_terms=("message authentication", "public key signature", "signature verification"),
        zh_aliases=("数字签名", "签名方案", "签名"),
        domain="cryptography",
    ),
    TopicEntry(
        canonical="program analysis",
        aliases=("static analysis", "dynamic analysis", "binary analysis"),
        subtopics=("deobfuscation", "symbolic execution", "program synthesis", "vulnerability detection"),
        related_terms=("fuzzing", "taint analysis", "runtime analysis", "exploit detection"),
        zh_aliases=("程序分析", "静态分析", "动态分析", "二进制分析"),
        domain="systems-security",
    ),
    TopicEntry(
        canonical="symbolic execution",
        aliases=("symbolic executor", "path exploration", "path prioritization"),
        subtopics=("path constraint solving", "constraint reasoning", "concolic execution"),
        related_terms=("program analysis", "binary analysis", "taint analysis", "fuzzing"),
        zh_aliases=("符号执行",),
        domain="systems-security",
    ),
    TopicEntry(
        canonical="vulnerability detection",
        aliases=("vulnerability analysis", "bug detection", "vulnerability discovery"),
        subtopics=("source code vulnerability analysis", "vulnerability validation", "code property graph"),
        related_terms=("program analysis", "static analysis", "fuzzing", "taint analysis"),
        zh_aliases=("漏洞检测", "漏洞分析", "漏洞发现"),
        domain="systems-security",
    ),
    TopicEntry(
        canonical="taint analysis",
        aliases=("static taint analysis", "taint-style vulnerability", "information flow analysis"),
        subtopics=("data-flow analysis", "taint tracking", "flow-sensitive analysis"),
        related_terms=("program analysis", "vulnerability detection", "static analysis"),
        zh_aliases=("污点分析",),
        domain="systems-security",
    ),
    TopicEntry(
        canonical="binary analysis",
        aliases=("binary code analysis", "binary reverse engineering", "disassembly"),
        subtopics=("binary lifting", "disassembler", "stripped binaries", "data-code separation"),
        related_terms=("program analysis", "deobfuscation", "symbolic execution"),
        zh_aliases=("二进制分析",),
        domain="systems-security",
    ),
    TopicEntry(
        canonical="fuzzing",
        aliases=("fuzzer", "fuzz testing", "coverage-guided fuzzing"),
        subtopics=("firmware fuzzing", "protocol fuzzing", "cpu fuzzing", "kernel fuzzing"),
        related_terms=("bug finding", "vulnerability hunting", "input generation", "rehosting"),
        zh_aliases=("模糊测试", "fuzz", "fuzzing"),
        domain="systems-security",
    ),
    TopicEntry(
        canonical="malware detection",
        aliases=("malware analysis", "packed executables detection", "android malware detection"),
        subtopics=("packer detection", "packed malware detection", "malware classification"),
        related_terms=("malware", "adversarial malware", "packed executables", "ransomware detection"),
        zh_aliases=("恶意软件检测", "恶意软件分析", "安卓恶意软件检测"),
        domain="security-ml",
    ),
    TopicEntry(
        canonical="web security",
        aliases=("browser security", "security headers", "dom security"),
        subtopics=("xss", "script gadgets", "cross-site leaks", "clickjacking"),
        related_terms=("web attacks", "browser inconsistencies", "dom injections"),
        zh_aliases=("Web安全", "Web 安全", "浏览器安全", "网页安全", "网站安全"),
        domain="systems-security",
    ),
    TopicEntry(
        canonical="adversarial machine learning",
        aliases=("adversarial ml", "data poisoning", "robustness certification"),
        subtopics=("adversarial attacks", "poisoning attacks", "robustness", "backdoor attacks", "model stealing", "membership inference"),
        related_terms=("certification", "backdoor", "transferable attacks", "student-teacher poisoning", "model extraction", "model stealing", "privacy attacks"),
        zh_aliases=("对抗机器学习", "对抗学习", "数据投毒", "投毒攻击", "中毒攻击", "后门攻击", "模型窃取", "成员推断", "鲁棒性认证"),
        domain="security-ml",
    ),
    TopicEntry(
        canonical="hardware security",
        aliases=("cpu security", "architecture security", "dma security"),
        subtopics=("risc-v security", "microarchitectural attacks", "dma race conditions"),
        related_terms=("firmware security", "embedded security", "side channel"),
        zh_aliases=("硬件安全", "体系结构安全", "CPU安全", "DMA安全"),
        domain="systems-security",
    ),
    TopicEntry(
        canonical="network security",
        aliases=("internet security", "routing security", "network attack defense"),
        subtopics=("bgp security", "routing attacks", "network measurement", "traffic security"),
        related_terms=("prefix hijack", "route origin validation", "network infrastructure", "denial of service"),
        zh_aliases=("网络安全", "互联网安全", "路由安全", "流量安全"),
        domain="systems-security",
    ),
    TopicEntry(
        canonical="systems security",
        aliases=("operating system security", "os security", "kernel security"),
        subtopics=("kernel compartmentalization", "trusted execution environments", "sandboxing", "memory isolation"),
        related_terms=("enclave security", "system hardening", "privilege separation", "secure isolation"),
        zh_aliases=("系统安全", "操作系统安全", "内核安全", "隔离安全"),
        domain="systems-security",
    ),
    TopicEntry(
        canonical="cyber-physical security",
        aliases=("cps security", "physical process security", "sensor security"),
        subtopics=("lidar spoofing", "signal injection", "electromagnetic interference", "wireless jamming"),
        related_terms=("autonomous driving security", "power system security", "industrial control security", "radio attacks"),
        zh_aliases=("信息物理安全", "传感器安全", "车联网安全", "工控安全"),
        domain="systems-security",
    ),
    TopicEntry(
        canonical="trusted execution security",
        aliases=("enclave security", "tee security", "trusted execution environments"),
        subtopics=("sgx security", "enclave isolation", "privilege separation"),
        related_terms=("confidential computing", "attestation", "secure enclaves"),
        zh_aliases=("可信执行安全", "TEE安全", "飞地安全", "机密计算安全"),
        domain="systems-security",
    ),
    TopicEntry(
        canonical="abuse and fraud detection",
        aliases=("online abuse detection", "fraud detection", "scam detection"),
        subtopics=("phishing detection", "harmful content detection", "domain abuse", "blocklist abuse"),
        related_terms=("brand abuse", "giveaway scams", "harmful memes", "email abuse"),
        zh_aliases=("滥用检测", "欺诈检测", "诈骗检测", "有害内容检测"),
        domain="human-factors",
    ),
    TopicEntry(
        canonical="usable security",
        aliases=("password security", "security usability", "privacy usability"),
        subtopics=("password management", "accessible security", "user security behavior"),
        related_terms=("human factors security", "password managers", "security accessibility"),
        zh_aliases=("可用安全", "密码安全", "安全可用性", "无障碍安全"),
        domain="human-factors",
    ),
    TopicEntry(
        canonical="iot security",
        aliases=("internet of things security", "smart device security", "embedded iot security"),
        subtopics=("device identification security", "iot attacks", "iot defense"),
        related_terms=("smart home security", "connected device security", "firmware security"),
        zh_aliases=("物联网安全", "IoT安全", "设备安全"),
        domain="systems-security",
    ),
    TopicEntry(
        canonical="ransomware",
        aliases=("ransomware attacks", "crypto-ransomware", "extortion malware"),
        subtopics=("database ransomware", "ransom campaigns", "data extortion"),
        related_terms=("malware detection", "incident response", "cybercrime"),
        zh_aliases=("勒索软件", "勒索攻击", "数据库勒索"),
        domain="security-ml",
    ),
    TopicEntry(
        canonical="internet measurement",
        aliases=("network measurement", "internet-wide measurement", "security measurement"),
        subtopics=("scanner analysis", "protocol measurement", "internet scanning"),
        related_terms=("measurement study", "large-scale measurement", "scanning infrastructure"),
        zh_aliases=("互联网测量", "网络测量", "安全测量"),
        domain="systems-security",
    ),
    TopicEntry(
        canonical="hardware attacks",
        aliases=("fault attacks", "side-channel attacks", "rowhammer"),
        subtopics=("rowhammer mitigation", "electromagnetic attacks", "signal injection"),
        related_terms=("microarchitectural attacks", "fault injection", "hardware exploitation"),
        zh_aliases=("硬件攻击", "故障攻击", "侧信道攻击", "Rowhammer"),
        domain="systems-security",
    ),
    TopicEntry(
        canonical="media authenticity and deepfakes",
        aliases=("deepfake detection", "synthetic media security", "media authenticity"),
        subtopics=("audio deepfakes", "voice conversion attacks", "harmful media detection"),
        related_terms=("multimodal safety", "content authenticity", "misinformation detection"),
        zh_aliases=("深度伪造检测", "媒体真实性", "音频深伪", "深伪安全"),
        domain="security-ml",
    ),
    TopicEntry(
        canonical="blockchain security",
        aliases=("cryptocurrency security", "consensus security", "distributed ledger security"),
        subtopics=("staking security", "smart contract security", "consensus attacks"),
        related_terms=("chain security", "cross-chain security", "blockchain protocols"),
        zh_aliases=("区块链安全", "共识安全", "智能合约安全"),
        domain="cryptography",
    ),
    TopicEntry(
        canonical="content moderation and platform integrity",
        aliases=("platform integrity", "content moderation security", "online integrity"),
        subtopics=("warning labels", "community notes", "hateful content", "captcha security"),
        related_terms=("inauthentic content", "bot mitigation", "harmful content", "platform abuse"),
        zh_aliases=("内容审核", "平台完整性", "平台治理", "验证码安全"),
        domain="human-factors",
    ),
    TopicEntry(
        canonical="privacy and security behavior",
        aliases=("security behavior", "privacy behavior", "user privacy and security"),
        subtopics=("smartphone theft", "security preparation", "incident response behavior"),
        related_terms=("human factors security", "privacy concerns", "recovery behavior"),
        zh_aliases=("隐私与安全行为", "用户安全行为", "用户隐私行为"),
        domain="human-factors",
    ),
    TopicEntry(
        canonical="ai model integrity and watermarking",
        aliases=("model watermarking", "ai watermarking", "model attribution"),
        subtopics=("rag watermarking", "concept shift attribution", "model provenance"),
        related_terms=("ownership verification", "training integrity", "inference integrity", "model attribution", "neural network watermarking"),
        zh_aliases=("模型水印", "AI模型完整性", "模型归因", "模型溯源"),
        domain="security-ml",
    ),
    TopicEntry(
        canonical="ai security",
        aliases=("llm security", "security of ai", "safe ai systems", "secure ai systems"),
        subtopics=("code generation security", "retrieval-augmented generation security", "model safeguards", "prompt injection", "jailbreaks", "data poisoning", "backdoor attacks", "model extraction", "membership inference", "prompt stealing", "model watermarking"),
        related_terms=("prompt injection", "prompt stealing", "prompt leakage", "system prompt", "rag security", "model misuse", "model attacks", "agent security", "tool-using agents", "training data poisoning", "backdoor defense", "pii extraction", "privacy leakage", "ownership verification", "adapter backdoor"),
        zh_aliases=("AI安全", "AI 安全", "大模型安全", "大模型 安全", "LLM安全", "LLM 安全"),
        domain="security-ml",
    ),
    TopicEntry(
        canonical="llm safety",
        aliases=("model safety", "youth safety", "safeguard model", "llm safety", "llm alignment safety"),
        subtopics=("harm detection", "content moderation", "safety benchmark", "refusal behavior", "jailbreak defense", "safety refusal"),
        related_terms=("risk benchmark", "safety evaluation", "harm mitigation", "policy compliance", "safe completion", "refusal consistency", "harmlessness"),
        zh_aliases=("LLM安全性", "LLM 安全性", "模型安全性", "大模型安全性", "模型安全", "LLM安全", "LLM 安全", "大模型安全"),
        domain="security-ml",
    ),
    TopicEntry(
        canonical="security governance",
        aliases=("cybersecurity regulations", "security compliance", "organizational security"),
        subtopics=("policy compliance", "regulatory security", "security programs"),
        related_terms=("security posture", "industry regulation", "governance"),
        zh_aliases=("安全治理", "网络安全治理", "安全合规", "安全监管"),
        domain="governance",
    ),
    TopicEntry(
        canonical="vulnerability management",
        aliases=("vulnerability scoring", "vulnerability prioritization", "risk scoring"),
        subtopics=("cvss", "remediation prioritization", "vulnerability assessment"),
        related_terms=("software vulnerability", "scoring systems", "security metrics"),
        zh_aliases=("漏洞管理", "漏洞评分", "漏洞优先级"),
        domain="governance",
    ),
    TopicEntry(
        canonical="usable security",
        aliases=("human factors security", "security perceptions", "privacy perceptions"),
        subtopics=("user studies", "security behavior", "privacy behavior"),
        related_terms=("user safety", "online risks", "interpersonal account compromise"),
        zh_aliases=("可用安全", "安全可用性", "人因安全"),
        domain="human-factors",
    ),
    TopicEntry(
        canonical="security training",
        aliases=("security awareness", "training effectiveness", "organizational training"),
        subtopics=("employee training", "security education", "training measurement"),
        related_terms=("10-k filings", "vendor claims", "training programs"),
        zh_aliases=("安全培训", "安全意识培训", "安全教育"),
        domain="human-factors",
    ),
)


def score_topic_entries(text: str) -> list[tuple[int, int, TopicEntry]]:
    lowered = (text or "").strip().lower()
    scored: list[tuple[int, int, TopicEntry]] = []
    for entry in TOPIC_TAXONOMY:
        score = 0
        canonical = entry.canonical.lower()
        alias_terms = [term.lower() for term in (*entry.aliases, *entry.zh_aliases)]
        subtopic_terms = [term.lower() for term in entry.subtopics]
        related_terms = [term.lower() for term in entry.related_terms]
        if canonical and canonical in lowered:
            score = max(score, 5)
        if any(term and term in lowered for term in alias_terms):
            score = max(score, 4)
        if any(term and term in lowered for term in subtopic_terms):
            score = max(score, 2)
        if any(term and term in lowered for term in related_terms):
            score = max(score, 1)
        if score > 0:
            scored.append((score, len(entry.canonical), entry))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    # If a broad parent topic only matched through subtopics while a more specific
    # child topic matched canonically/alias-wise, prefer the specific topic.
    specific_terms = {
        entry.canonical.lower()
        for score, _, entry in scored
        if score >= 4
    }
    filtered: list[tuple[int, int, TopicEntry]] = []
    for score, length, entry in scored:
        if score <= 2 and any(term.lower() in specific_terms for term in entry.subtopics):
            continue
        filtered.append((score, length, entry))
    return filtered


def detect_topic_entries(text: str) -> list[TopicEntry]:
    return [entry for _, _, entry in score_topic_entries(text)]


def expand_topics(text: str, *, generic: bool = False, limit: int = 12) -> list[str]:
    scored = score_topic_entries(text)
    expanded: list[str] = []
    for index, (score, _, entry) in enumerate(scored):
        expanded.append(entry.canonical)
        expanded.extend(entry.aliases)
        expanded.extend(entry.zh_aliases)

        is_primary = index == 0
        broad_parent = entry.canonical in {
            "program analysis",
            "privacy-preserving computation",
            "malware detection",
        }

        if score >= 4:
            if generic and broad_parent and is_primary:
                expanded.extend(entry.subtopics[:2])
                expanded.extend(entry.related_terms[:1])
            else:
                expanded.extend(entry.subtopics)
                if generic and is_primary:
                    expanded.extend(entry.related_terms)
        elif score >= 2:
            expanded.extend(entry.subtopics[:2])
            if generic and is_primary:
                expanded.extend(entry.related_terms[:2])
        elif generic and is_primary:
            expanded.extend(entry.related_terms[:2])

    deduped: list[str] = []
    seen: set[str] = set()
    for item in expanded:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(item.strip())
        if len(deduped) >= limit:
            break
    return deduped


def infer_query_type_from_topics(text: str) -> str | None:
    detected = detect_topic_entries(text)
    if not detected:
        return None

    lowered = (text or "").strip().lower()
    if any(alias in lowered for alias in ("symbolic execution", "vulnerability detection", "taint analysis", "binary analysis", "符号执行", "漏洞检测", "污点分析", "二进制分析")):
        return "specific"
    if len(lowered.split()) <= 4 or any(alias in text for alias in ("密码学", "同态加密", "零知识证明", "多方计算")):
        return "generic"
    return None
