"""FR-071 补齐（终检 §六-1）：SAML 协议形态——解析 + 注入式验签。"""

from __future__ import annotations

import base64

import pytest

from vasta_protocols.errors import VastaError
from vastacore.governance.saml import (
    parse_saml_response,
    verify_saml_response,
)

RESPONSE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol">
  <saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">
    <saml:Issuer>https://idp.example.com</saml:Issuer>
    <saml:Subject>
      <saml:NameID>alice@example.com</saml:NameID>
    </saml:Subject>
    <saml:Conditions>
      <saml:AudienceRestriction>
        <saml:Audience>https://vasta.example.com</saml:Audience>
      </saml:AudienceRestriction>
    </saml:Conditions>
    <saml:AttributeStatement>
      <saml:Attribute Name="role">
        <saml:AttributeValue>operator</saml:AttributeValue>
      </saml:Attribute>
    </saml:AttributeStatement>
  </saml:Assertion>
</samlp:Response>
"""


def b64(xml: str) -> str:
    return base64.b64encode(xml.encode()).decode()


def ok_verifier(response_xml: str, assertion_xml: str) -> bool:
    return True


class TestParse:
    def test_parse_extracts_assertion(self) -> None:
        response_xml, assertion_xml, _ = parse_saml_response(b64(
            RESPONSE_XML))
        assert "idp.example.com" in response_xml
        assert "Assertion" in assertion_xml

    def test_bad_base64_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            parse_saml_response("not-base64!!!")
        assert e.value.code == "identity.saml_bad_base64"

    def test_doctype_injection_rejected(self) -> None:
        evil = RESPONSE_XML.replace(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
            "<?xml version=\"1.0\"?><!DOCTYPE foo [<!ENTITY xxe "
            "SYSTEM \"file:///etc/passwd\">]>")
        with pytest.raises(VastaError) as e:
            parse_saml_response(b64(evil))
        assert e.value.code == "identity.saml_dangerous_xml"

    def test_missing_assertion_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            parse_saml_response(b64("<samlp:Response "
                                    "xmlns:samlp='urn:oasis:names:tc:"
                                    "SAML:2.0:protocol'/>"))
        assert e.value.code == "identity.saml_no_assertion"


class TestVerify:
    def test_valid_response_yields_claims(self) -> None:
        claims = verify_saml_response(
            b64(RESPONSE_XML), verifier=ok_verifier,
            expected_audience="https://vasta.example.com",
            expected_issuer="https://idp.example.com")
        assert claims.name_id == "alice@example.com"
        assert claims.attributes["role"] == "operator"

    def test_bad_signature_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            verify_saml_response(
                b64(RESPONSE_XML),
                verifier=lambda _r, _a: False,
                expected_audience="https://vasta.example.com",
                expected_issuer="https://idp.example.com")
        assert e.value.code == "identity.saml_bad_signature"

    def test_issuer_mismatch_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            verify_saml_response(
                b64(RESPONSE_XML), verifier=ok_verifier,
                expected_audience="https://vasta.example.com",
                expected_issuer="https://other-idp.example.com")
        assert e.value.code == "identity.saml_issuer_mismatch"

    def test_audience_mismatch_rejected(self) -> None:
        with pytest.raises(VastaError) as e:
            verify_saml_response(
                b64(RESPONSE_XML), verifier=ok_verifier,
                expected_audience="https://wrong-sp.example.com",
                expected_issuer="https://idp.example.com")
        assert e.value.code == "identity.saml_audience_mismatch"
