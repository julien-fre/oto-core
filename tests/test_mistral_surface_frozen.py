"""La surface de `MistralClient` est un CONTRAT, pas un détail.

Un consommateur épingle la lib par tag et importe `oto.tools.mistral` : renommer une méthode, changer un défaut ou
déplacer un symbole casse un consommateur au bump du pin, loin d'ici. Ce test fige les membres AVEC leurs signatures,
les noms importables, la correspondance entre les fonctions de la description et les méthodes du client, et la taille
des modules du paquet.

⚠️ Ce test échoue si tu ajoutes une méthode : c'est voulu — mets à jour la constante EN CONNAISSANCE DE CAUSE, jamais
par réflexe pour faire passer le vert.
"""
import inspect
import pathlib

import yaml

import oto.tools.mistral as pkg
import oto.tools.mistral.client as mod
import oto.tools.mistral.transcription as transcription

ROOT = pathlib.Path(__file__).resolve().parent.parent
DESCRIPTION = ROOT / "connectors" / "mistral" / "connector.yaml"

EXPECTED_MEMBERS = {
    '_get_headers': "(self) -> dict",
    'chat': "(self, messages: List[Dict[str, str]], temperature: float = 0.7, max_tokens: int = 2048, json_mode: bool = False, model: str = None) -> Dict[str, Any]",
    'chat_with_tools': "(self, messages: List[Dict], tools: List[Dict], temperature: float = 0.3, max_tokens: int = 2048, model: str = None) -> Dict[str, Any]",
    'complete': "(self, system_prompt: str, user_prompt: str, temperature: float = 0.7, max_tokens: int = 2048, json_mode: bool = False, model: str = None) -> str",
    'complete_json': "(self, system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 2048, model: str = None) -> Dict[str, Any]",
    'list_models': "(self) -> Dict[str, Any]",
    'transcribe': "(self, audio: bytes, filename: str, *, mime: Optional[str] = None, language: Optional[str] = None, timestamps: bool = False, diarize: bool = False, context_bias: Union[Iterable[str], str, NoneType] = None, model: Optional[str] = None, timeout: tuple = (10, 300)) -> Dict[str, Any]",
}

#: Méthodes publiques que la description ne porte pas (motifs : `LEFT_OUT` de `tests/test_mistral_description.py`).
OUTSIDE_DESCRIPTION = {"chat", "complete", "complete_json", "chat_with_tools", "list_models"}


def _members():
    return {n: str(inspect.signature(getattr(mod.MistralClient, n)))
            for n in dir(mod.MistralClient)
            if not n.startswith("__") and callable(getattr(mod.MistralClient, n))}


def _functions():
    return {f["name"]: f for f in yaml.safe_load(DESCRIPTION.read_text(encoding="utf-8"))["functions"]}


def test_membres_et_signatures_figes():
    assert _members() == EXPECTED_MEMBERS


def test_noms_importables():
    assert pkg.__all__ == ["MistralClient", "DEFAULT_TRANSCRIPTION_MODEL", "context_bias_terms",
                           "normalize_transcription"]
    assert mod.MistralClient.BASE_URL == "https://api.mistral.ai/v1"
    assert mod.TRANSCRIPTION_TIMEOUT == (10, 300)
    for name in ("DEFAULT_TRANSCRIPTION_MODEL", "MAX_CONTEXT_BIAS_TERMS", "MIN_TERM_LENGTH", "context_bias_terms",
                 "normalize_transcription"):
        assert hasattr(transcription, name), name


def test_une_fonction_decrite_est_une_methode_du_meme_nom():
    public = {n for n in EXPECTED_MEMBERS if not n.startswith("_")}
    assert set(_functions()) == public - OUTSIDE_DESCRIPTION


def test_aucun_module_de_500_lignes_ou_plus():
    package = pathlib.Path(mod.__file__).parent
    for path in package.rglob("*.py"):
        assert len(path.read_text(encoding="utf-8").splitlines()) < 500, path
