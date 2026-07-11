"""
Testes para entity_resolver.py

Cobre:
  - normalize_name
  - score_club_candidate (Sporting CP vs Sporting Gijón, Al Ahli, Inter)
  - score_player_candidate (Francisco Trincão vs Francisco Conceição)
  - _pick_winner (thresholds de score e gap)
  - Casos de rejeição (nome genérico sem contexto, sobrenome incompatível)

Execute:
  cd saudi-football-monitor
  python -m pytest tests/test_entity_resolver.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from entity_resolver import (
    normalize_name,
    score_club_candidate,
    score_player_candidate,
    score_player_club_pair,
    _pick_winner,
    _versioned_ctx,
    EntityContext,
    CandidateScore,
    MIN_SCORE,
    MIN_GAP,
    AMBIGUOUS_CLUB_NAMES,
    RESOLVER_VERSION,
    W_CLUB_AMBIG_NO_CTX,
    W_JOINT_CURRENT,
    W_JOINT_RECENT,
    W_JOINT_COMPAT,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_club(af_id: str, name: str, country: str) -> dict:
    return {"team": {"id": int(af_id), "name": name, "country": country}}


def make_player(af_id: str, name: str, nationality: str = "",
                position: str = "", age: int | None = None) -> dict:
    p = {"id": int(af_id), "name": name, "nationality": nationality,
         "position": position}
    if age is not None:
        p["age"] = age
    return {"player": p}


# ── normalize_name ────────────────────────────────────────────────────────────

class TestNormalizeName:
    def test_strips_accents(self):
        assert normalize_name("Trincão") == "trincao"
        assert normalize_name("Sporting CP") == "sporting cp"

    def test_lowercase(self):
        assert normalize_name("AL AHLI") == "al ahli"

    def test_removes_punctuation(self):
        assert normalize_name("Al-Ahli Jeddah") == "al ahli jeddah"

    def test_collapses_spaces(self):
        assert normalize_name("  Al   Nassr  ") == "al nassr"

    def test_empty(self):
        assert normalize_name("") == ""
        assert normalize_name(None) == ""

    def test_arabic_transliteration(self):
        # Nomes comuns em transliteração
        assert normalize_name("Mohammed Al-Owais") == "mohammed al owais"


# ── score_club_candidate — Sporting ──────────────────────────────────────────

class TestSportingDisambiguation:
    """
    Sporting é ambíguo: Sporting CP (Portugal, id=228) vs Sporting Gijón (Espanha, id=558).
    Com contexto de Portugal → CP deve vencer com folga.
    Com contexto de Espanha → Gijón deve vencer.
    Sem contexto → ambos ficam baixos (nome genérico penalizado).
    """

    sporting_cp    = make_club("228", "Sporting CP", "Portugal")
    sporting_gijon = make_club("558", "Sporting Gijón", "Spain")
    sporting_kc    = make_club("1601", "Sporting Kansas City", "USA")

    def test_portugal_context_picks_cp(self):
        ctx = EntityContext(country="Portugal")
        score_cp    = score_club_candidate(self.sporting_cp, "Sporting", ctx)
        score_gijon = score_club_candidate(self.sporting_gijon, "Sporting", ctx)
        # CP tem country_correct (+30), Gijón tem country_incompatible (-40)
        assert score_cp.score > score_gijon.score, (
            f"CP={score_cp.score} deve superar Gijón={score_gijon.score} com ctx=Portugal"
        )
        # Diferença deve ser suficiente para resolução
        gap = score_cp.score - score_gijon.score
        assert gap >= MIN_GAP, f"Gap={gap:.1f} insuficiente para resolução (min={MIN_GAP})"
        assert "country_correct" in score_cp.breakdown
        assert "country_incompatible" in score_gijon.breakdown

    def test_spain_context_picks_gijon(self):
        ctx = EntityContext(country="Spain")
        score_cp    = score_club_candidate(self.sporting_cp, "Sporting", ctx)
        score_gijon = score_club_candidate(self.sporting_gijon, "Sporting Gijón", ctx)
        assert score_gijon.score > score_cp.score, (
            f"Gijón={score_gijon.score} deve superar CP={score_cp.score} com ctx=Spain"
        )
        assert "country_correct" in score_gijon.breakdown
        assert "country_incompatible" in score_cp.breakdown

    def test_no_context_penalizes_ambiguous_name(self):
        ctx = EntityContext()  # sem país
        score_cp    = score_club_candidate(self.sporting_cp, "Sporting", ctx)
        score_gijon = score_club_candidate(self.sporting_gijon, "Sporting", ctx)
        # Ambos ficam baixos — nome "sporting" está em AMBIGUOUS_CLUB_NAMES
        # Nenhum deve atingir MIN_SCORE sem contexto
        assert score_cp.score < MIN_SCORE, (
            f"CP não deveria resolver sem contexto: score={score_cp.score}"
        )
        assert "ambiguous_name_no_context" in score_cp.breakdown

    def test_sporting_cp_exact_name_resolves(self):
        """'Sporting CP' (com sufixo) é suficientemente específico com contexto Portugal."""
        ctx = EntityContext(country="Portugal")
        score_cp    = score_club_candidate(self.sporting_cp, "Sporting CP", ctx)
        score_gijon = score_club_candidate(self.sporting_gijon, "Sporting CP", ctx)
        # "Sporting CP" não está em AMBIGUOUS_CLUB_NAMES
        assert "sporting cp" not in AMBIGUOUS_CLUB_NAMES
        assert score_cp.score >= MIN_SCORE, f"CP com nome exato+ctx deveria resolver: {score_cp.score}"
        assert score_cp.score > score_gijon.score


# ── score_club_candidate — Al Ahli ───────────────────────────────────────────

class TestAlAhliDisambiguation:
    """
    Al Ahli ambíguo: Al Ahli Jeddah (Saudi, id=2929) vs Al Ahli Dubai (UAE) vs Al Ahli Cairo (Egypt).
    Com contexto Saudi Arabia → Jeddah deve vencer.
    """

    al_ahli_jeddah = make_club("2929", "Al-Ahli Saudi FC", "Saudi Arabia")
    al_ahli_dubai  = make_club("2914", "Al Ahli Dubai",   "UAE")
    al_ahli_cairo  = make_club("440",  "Al Ahly",         "Egypt")

    def test_saudi_context_picks_jeddah(self):
        ctx = EntityContext(country="Saudi Arabia")
        score_jeddah = score_club_candidate(self.al_ahli_jeddah, "Al Ahli", ctx)
        score_dubai  = score_club_candidate(self.al_ahli_dubai,  "Al Ahli", ctx)
        score_cairo  = score_club_candidate(self.al_ahli_cairo,  "Al Ahli", ctx)
        assert score_jeddah.score > score_dubai.score, (
            f"Jeddah={score_jeddah.score} deve superar Dubai={score_dubai.score}"
        )
        assert score_jeddah.score > score_cairo.score
        assert "country_correct" in score_jeddah.breakdown
        assert "country_incompatible" in score_dubai.breakdown

    def test_no_context_stays_ambiguous(self):
        ctx = EntityContext()
        score_jeddah = score_club_candidate(self.al_ahli_jeddah, "Al Ahli", ctx)
        # Sem contexto, "al ahli" ∈ AMBIGUOUS_CLUB_NAMES → penalidade
        assert "ambiguous_name_no_context" in score_jeddah.breakdown


# ── score_player_candidate — Francisco Trincão ───────────────────────────────

class TestFranciscoTrincao:
    """
    Trincão (id=279006) vs Francisco Conceição (id=284497).
    Com squad_member=True para Trincão (encontrado no Sporting CP) → deve vencer.
    Sem squad → sobrenome deve distinguir.
    """

    trincao     = make_player("279006", "Francisco Trincão",   "Portugal", "Attacker", 24)
    conceicao   = make_player("284497", "Francisco Conceição", "Portugal", "Attacker", 22)

    ctx_pt = EntityContext(nationality="português", position="Atacante", age=24)

    def test_squad_member_wins(self):
        """Trincão encontrado no elenco do Sporting CP (squad_member=True)."""
        score_trincao   = score_player_candidate(self.trincao,   "Francisco Trincão", self.ctx_pt, found_via_team=True)
        score_conceicao = score_player_candidate(self.conceicao, "Francisco Trincão", self.ctx_pt, found_via_team=False)
        assert score_trincao.score > score_conceicao.score, (
            f"Trincao={score_trincao.score} deve superar Conceicao={score_conceicao.score}"
        )
        assert "squad_member" in score_trincao.breakdown
        assert "squad_member" not in score_conceicao.breakdown

    def test_surname_distinguishes_without_squad(self):
        """Sem squad: sobrenome 'Trincão' vs 'Conceição' — similares mas distintos."""
        score_trincao   = score_player_candidate(self.trincao,   "Francisco Trincão", self.ctx_pt, found_via_team=False)
        score_conceicao = score_player_candidate(self.conceicao, "Francisco Trincão", self.ctx_pt, found_via_team=False)
        # "trincao" vs "conceicao" têm baixa similaridade → Trincão vence
        assert score_trincao.score > score_conceicao.score

    def test_age_contributes(self):
        """Trincão com idade correta (24) recebe bônus de idade."""
        score_trincao   = score_player_candidate(self.trincao,   "Francisco Trincão", self.ctx_pt, found_via_team=True)
        score_conceicao = score_player_candidate(self.conceicao, "Francisco Trincão", self.ctx_pt, found_via_team=True)
        assert "age_match" in score_trincao.breakdown
        # Conceição tem 22, contexto é 24 → diferença de 2, ainda dentro da tolerância
        # Mas Trincão tem 24 = correspondência exata

    def test_full_name_resolves_with_squad(self):
        """Com nome completo e squad, deve atingir MIN_SCORE."""
        score = score_player_candidate(self.trincao, "Francisco Trincão", self.ctx_pt, found_via_team=True)
        assert score.score >= MIN_SCORE, f"Trincao com squad deveria resolver: {score.score}"

    def test_wrong_surname_rejected(self):
        """Candidato com sobrenome muito diferente deve ser rejeitado."""
        irrelevant = make_player("999", "Cristiano Ronaldo", "Portugal", "Attacker", 40)
        score = score_player_candidate(irrelevant, "Francisco Trincão", self.ctx_pt, found_via_team=False)
        assert score.score <= -900, f"Ronaldo deveria ser rejeitado por sobrenome: {score.score}"
        assert "rejected" in score.breakdown


# ── _pick_winner ──────────────────────────────────────────────────────────────

class TestPickWinner:
    def test_resolves_when_score_and_gap_met(self):
        candidates = [
            CandidateScore("228", "Sporting CP", "Portugal", 92.0, {}),
            CandidateScore("558", "Sporting Gijón", "Spain", 30.0, {}),
        ]
        result = _pick_winner(candidates)
        assert result.status == "resolved"
        assert result.af_id == "228"
        assert result.gap == 62.0

    def test_ambiguous_when_gap_too_small(self):
        candidates = [
            CandidateScore("1", "Club A", "X", 80.0, {}),
            CandidateScore("2", "Club B", "Y", 65.0, {}),
        ]
        result = _pick_winner(candidates)
        assert result.status == "ambiguous"
        assert result.af_id is None

    def test_ambiguous_when_score_too_low(self):
        candidates = [
            CandidateScore("1", "Club A", "X", 50.0, {}),
            CandidateScore("2", "Club B", "Y", 20.0, {}),
        ]
        result = _pick_winner(candidates)
        assert result.status == "ambiguous"
        assert result.af_id is None

    def test_unresolved_when_no_candidates(self):
        result = _pick_winner([])
        assert result.status == "unresolved"
        assert result.af_id is None

    def test_unresolved_when_all_rejected(self):
        rejected = CandidateScore("1", "X", "Y", -999.0, {"rejected": "surname_sim=0.1"})
        result = _pick_winner([rejected])
        assert result.status == "unresolved"

    def test_single_candidate_needs_min_score(self):
        """Único candidato: resolve se score >= 75 (gap = score - 0 = score)."""
        good = CandidateScore("228", "Sporting CP", "Portugal", 92.0, {})
        result = _pick_winner([good])
        assert result.status == "resolved"
        assert result.gap == 92.0

    def test_top_candidates_sorted(self):
        candidates = [
            CandidateScore("3", "C", "Z", 40.0, {}),
            CandidateScore("1", "A", "X", 90.0, {}),
            CandidateScore("2", "B", "Y", 55.0, {}),
        ]
        result = _pick_winner(candidates)
        assert result.af_id == "1"
        assert result.candidates[0].af_id == "1"
        assert result.candidates[1].af_id == "2"


# ── Casos específicos adicionais ──────────────────────────────────────────────

class TestInterAmbiguity:
    """Inter é ambíguo: Inter Milan (Itália) vs Inter Miami (EUA) vs centenas de outros."""

    inter_milan = make_club("505", "Inter", "Italy")
    inter_miami = make_club("9596", "Inter Miami", "USA")

    def test_italy_context_picks_milan(self):
        ctx = EntityContext(country="Italy")
        score_milan = score_club_candidate(self.inter_milan, "Inter", ctx)
        score_miami = score_club_candidate(self.inter_miami, "Inter", ctx)
        assert score_milan.score > score_miami.score
        gap = score_milan.score - score_miami.score
        assert gap >= MIN_GAP

    def test_no_context_inter_ambiguous(self):
        ctx = EntityContext()
        score_milan = score_club_candidate(self.inter_milan, "Inter", ctx)
        # "inter" ∈ AMBIGUOUS_CLUB_NAMES → penalidade
        assert "ambiguous_name_no_context" in score_milan.breakdown
        assert score_milan.score < MIN_SCORE


class TestNacionalAmbiguity:
    """Nacional é ambíguo: Club Nacional (Uruguai) vs Nacional Madeira (Portugal)."""

    nacional_ury = make_club("1024", "Club Nacional de Football", "Uruguay")
    nacional_mad = make_club("2282", "Nacional",                  "Portugal")

    def test_uruguay_context(self):
        ctx = EntityContext(country="Uruguay")
        score_ury = score_club_candidate(self.nacional_ury, "Nacional", ctx)
        score_mad = score_club_candidate(self.nacional_mad, "Nacional", ctx)
        assert score_ury.score > score_mad.score

    def test_no_context_stays_ambiguous(self):
        ctx = EntityContext()
        score = score_club_candidate(self.nacional_ury, "Nacional", ctx)
        assert score.score < MIN_SCORE


class TestQasimLajami:
    """Qasim Lajami: transliteração árabe divergente."""

    lajami      = make_player("200001", "Qasim Al-Lajami",  "Saudi Arabia", "Midfielder", 26)
    lajami_alt  = make_player("200001", "Kassem Lajami",    "Saudi Arabia", "Midfielder", 26)
    lajami_alt2 = make_player("200001", "Qasim Lajami",     "Saudi Arabia", "Midfielder", 26)

    ctx = EntityContext(nationality="saudita", position="Volante")

    def test_exact_match_resolves(self):
        score = score_player_candidate(self.lajami_alt2, "Qasim Lajami", self.ctx, found_via_team=True)
        assert score.score >= MIN_SCORE, f"Score={score.score}"

    def test_variant_spelling_accepted(self):
        """'kassem' vs 'qasim' — sobrenome 'lajami' é igual, score deve ser OK."""
        score = score_player_candidate(self.lajami_alt, "Qasim Lajami", self.ctx, found_via_team=True)
        # Sobrenome "lajami" == "lajami" → surname_exact (+25)
        assert "surname_exact" in score.breakdown
        assert score.score >= MIN_SCORE

    def test_al_prefix_stripped_variant(self):
        """'al-lajami' vs 'lajami' — normalização remove 'al-'."""
        score = score_player_candidate(self.lajami, "Qasim Lajami", self.ctx, found_via_team=True)
        # Sobrenome alvo "lajami", candidato "al lajami" → al prefix normalizado
        # _name_variants("Qasim Lajami") inclui "lajami" como variante
        # score ainda deve ser razoável pelo squad_member
        assert score.score > 0


class TestScoreBreakdownExplainability:
    """Verifica que todos os scores têm breakdown explicável (auditável)."""

    def test_club_score_has_breakdown(self):
        ctx = EntityContext(country="Portugal")
        score = score_club_candidate(
            make_club("228", "Sporting CP", "Portugal"), "Sporting CP", ctx
        )
        assert len(score.breakdown) > 0
        # Total deve ser soma do breakdown
        total_from_breakdown = sum(score.breakdown.values())
        assert abs(score.score - total_from_breakdown) < 0.1, (
            f"score={score.score} ≠ sum(breakdown)={total_from_breakdown}"
        )

    def test_player_score_has_breakdown(self):
        ctx = EntityContext(nationality="português", position="Atacante", age=24)
        player = make_player("279006", "Francisco Trincão", "Portugal", "Attacker", 24)

        score = score_player_candidate(player, "Francisco Trincao", ctx)
        assert len(score.breakdown) > 0


# ── New tests: joint resolution, cache versioning, global search ──────────────

class TestJointResolutionScoring:
    """Testa score_player_club_pair (bonus de vinculo jogador-clube)."""

    def test_current_season_gives_max_bonus(self):
        relations = [{"team_id": "228", "season": 2025}]
        bonus = score_player_club_pair(None, "228", relations, article_year="2025")
        assert bonus == W_JOINT_CURRENT  # 70.0

    def test_delta_one_gives_recent_bonus(self):
        relations = [{"team_id": "228", "season": 2024}]
        bonus = score_player_club_pair(None, "228", relations, article_year="2025")
        assert bonus == W_JOINT_RECENT  # 45.0

    def test_delta_three_gives_compat_bonus(self):
        relations = [{"team_id": "228", "season": 2022}]
        bonus = score_player_club_pair(None, "228", relations, article_year="2025")
        assert bonus == W_JOINT_COMPAT  # 35.0

    def test_gijon_gets_no_bonus(self):
        relations = [{"team_id": "228", "season": 2025}]  # 228 = Sporting CP
        bonus = score_player_club_pair(None, "939", relations, article_year="2025")  # 939 = Gijon
        assert bonus == 0.0

    def test_empty_relations_returns_zero(self):
        assert score_player_club_pair(None, "228", [], article_year="2025") == 0.0

    def test_multiple_relations_takes_best(self):
        relations = [
            {"team_id": "228", "season": 2022},  # delta=3 -> COMPAT=35
            {"team_id": "228", "season": 2025},  # delta=0 -> CURRENT=70
        ]
        bonus = score_player_club_pair(None, "228", relations, article_year="2025")
        assert bonus == W_JOINT_CURRENT  # 70.0

    def test_joint_score_raises_sporting_cp_above_min_score(self):
        """Sporting CP com vinculo atual: score ajustado deve >= MIN_SCORE."""
        ctx = EntityContext()  # sem pais
        s_cp  = score_club_candidate(make_club("228", "Sporting CP", "Portugal"), "Sporting", ctx)
        s_gij = score_club_candidate(make_club("939", "Sporting de Gijon", "Spain"), "Sporting", ctx)

        relations = [{"team_id": "228", "season": 2025}]
        bonus = score_player_club_pair(None, "228", relations, article_year="2025")
        ambig_penalty = s_cp.breakdown.get("ambiguous_name_no_context", 0.0)

        adjusted_cp_score = s_cp.score - ambig_penalty + bonus
        assert adjusted_cp_score >= MIN_SCORE, (
            f"Sporting CP ajustado ({adjusted_cp_score:.1f}) deve ser >= {MIN_SCORE}"
        )
        assert adjusted_cp_score > s_gij.score + MIN_GAP


class TestSportingAmbiguousNoPlayer:
    """Sporting sem contexto e sem jogador -> ambiguo."""

    def test_sporting_alone_no_context_is_ambiguous(self):
        ctx = EntityContext()
        s_cp  = score_club_candidate(make_club("228", "Sporting CP",       "Portugal"), "Sporting", ctx)
        s_gij = score_club_candidate(make_club("939", "Sporting de Gijon", "Spain"),    "Sporting", ctx)
        result = _pick_winner([s_cp, s_gij])
        assert result.status in ("ambiguous", "unresolved")
        assert result.af_id is None


class TestPlayerResolvedClubAmbiguous:
    """Score do jogador e independente do clube estar ambiguo."""

    def test_player_score_without_club_id(self):
        ctx = EntityContext(nationality="portugues")
        player = make_player("279006", "Francisco Trincao", "Portugal", "Attacker", 24)
        score = score_player_candidate(player, "Trincao", ctx, found_via_team=False)
        assert "squad_member" not in score.breakdown
        assert score.score > 0.0


class TestNoExternalSearchForAmbiguousClub:
    """Nome ambiguo sem contexto deve permanecer ambiguo."""

    def test_sporting_raw_name_ambiguous_without_context(self):
        ctx = EntityContext()
        s_cp  = score_club_candidate(make_club("228", "Sporting CP",       "Portugal"), "Sporting", ctx)
        s_gij = score_club_candidate(make_club("939", "Sporting de Gijon", "Spain"),    "Sporting", ctx)
        result = _pick_winner([s_cp, s_gij])
        assert result.status in ("ambiguous", "unresolved")
        assert result.af_id is None


class TestCacheVersion:
    """Versao de cache v3 isola entradas antigas."""

    def test_resolver_version_is_v3(self):
        from entity_resolver import RESOLVER_VERSION
        assert RESOLVER_VERSION == "v3"

    def test_versioned_ctx_prefix(self):
        assert _versioned_ctx("Portugal") == "v3|Portugal"

    def test_versioned_ctx_empty(self):
        assert _versioned_ctx("") == "v3|"

    def test_old_key_differs_from_new(self):
        assert "Portugal" != _versioned_ctx("Portugal")


class TestAmbiguousClubPlaceholder:
    """Clubes ambiguos devem permanecer ambiguos; contexto adequado resolve."""

    def test_two_close_scores_stay_ambiguous(self):
        c1 = CandidateScore(af_id="1", name="Inter Milan", country="Italy", score=60.0, breakdown={})
        c2 = CandidateScore(af_id="2", name="Inter Miami", country="USA",   score=58.0, breakdown={})
        result = _pick_winner([c1, c2])
        assert result.status == "ambiguous"
        assert result.af_id is None

    def test_adequate_gap_resolves(self):
        c1 = CandidateScore(af_id="1", name="Sporting CP",    country="Portugal", score=80.0, breakdown={})
        c2 = CandidateScore(af_id="2", name="Sporting Gijon", country="Spain",    score=50.0, breakdown={})
        result = _pick_winner([c1, c2])
        assert result.status == "resolved"
        assert result.af_id == "1"

    def test_al_ahli_saudi_context_resolves(self):
        ctx = EntityContext(country="Saudi Arabia")
        c_jeddah = score_club_candidate(
            make_club("2932", "Al-Ahli Saudi FC", "Saudi Arabia"), "Al Ahli", ctx
        )
        c_egypt = score_club_candidate(
            make_club("436", "Al Ahli Cairo", "Egypt"), "Al Ahli", ctx
        )
        assert c_jeddah.score > c_egypt.score


class TestScorePlayerClubPairEdgeCases:
    """Casos extremos de score_player_club_pair."""

    def test_distant_history(self):
        from entity_resolver import W_JOINT_DISTANT
        relations = [{"team_id": "228", "season": 2018}]
        bonus = score_player_club_pair(None, "228", relations, article_year="2025")
        assert bonus == W_JOINT_DISTANT  # 20.0

    def test_none_season_gets_distant_bonus(self):
        from entity_resolver import W_JOINT_DISTANT
        relations = [{"team_id": "228", "season": None}]
        bonus = score_player_club_pair(None, "228", relations, article_year="2025")
        assert bonus == W_JOINT_DISTANT

    def test_different_club_no_bonus(self):
        relations = [{"team_id": "939", "season": 2025}]
        bonus = score_player_club_pair(None, "228", relations, article_year="2025")
        assert bonus == 0.0

    def test_missing_club_af_id_returns_zero(self):
        relations = [{"team_id": "228", "season": 2025}]
        assert score_player_club_pair(None, "", relations, article_year="2025") == 0.0

    def test_empty_relations_list_returns_zero(self):
        assert score_player_club_pair(None, "228", [], article_year="2025") == 0.0
