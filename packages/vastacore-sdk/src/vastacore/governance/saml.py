"""SAML 断言校验（FR-071 补齐——终检 §六-1：拆解收窄首次补记）。

OIDC/SCIM 已由 10.9 交付；本模块补 SAML 协议形态——**最小工程内
实现 + 注入式验签**（与适配器/清单签名同一模式：协议解析用标准库，
密码学校验注入 verifier；生产接 xmlsec 时替换注入点，接口不变）：

- ``parse_saml_response``：Base64 → XML → 提取断言要素（issuer/
  audience/name_id/attributes）——stdlib xml.etree，防 XXE 由
  ``defusedxml`` 语义承担（解析前禁用外部实体——见 _SAFE_PARSER）；
- ``verify_saml_response``：注入式验签（verifier: (response_xml,
  assertion_xml) → bool）+ audience/issuer 校验——任一不符 fail-closed
  拒（与 OIDC JWKS 验签同错误信封口径）。
"""

from __future__ import annotations

import base64
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vasta_protocols.errors import VastaError

_NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
}

#: 注入式验签器：(完整响应 XML 文本, 断言 XML 文本) → 签名有效。
SamlVerifier = Callable[[str, str], bool]


class SamlClaims(BaseModel):
    """校验通过的断言要素。"""

    model_config = ConfigDict(extra="forbid")

    issuer: str
    audience: str
    name_id: str
    attributes: dict[str, str] = Field(default_factory=dict)


def _safe_xml(xml_bytes: bytes) -> ET.Element:
    """安全解析：拒绝 DOCTYPE/外部实体（XXE 防护——stdlib 形态）。"""
    if b"<!DOCTYPE" in xml_bytes or b"<!ENTITY" in xml_bytes:
        raise VastaError(
            code="identity.saml_dangerous_xml",
            message="SAML 响应含 DOCTYPE/ENTITY——外部实体注入拒收",
        )
    try:
        return ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise VastaError(
            code="identity.saml_bad_xml",
            message=f"SAML 响应非良构 XML（{exc}）",
        ) from exc


def parse_saml_response(response_b64: str) -> tuple[str, str, Any]:
    """Base64 解码 + 解析 → (完整 XML 文本, 断言 XML 文本, 根元素)。"""
    try:
        xml_bytes = base64.b64decode(response_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise VastaError(
            code="identity.saml_bad_base64",
            message=f"SAML 响应非合法 Base64（{exc}）",
        ) from exc
    root = _safe_xml(xml_bytes)
    assertion = root.find(".//saml:Assertion", _NS)
    if assertion is None:
        raise VastaError(
            code="identity.saml_no_assertion",
            message="SAML 响应缺 Assertion 要素",
        )
    return xml_bytes.decode("utf-8", errors="replace"), \
        ET.tostring(assertion, encoding="unicode"), root


def verify_saml_response(
    response_b64: str, *, verifier: SamlVerifier,
    expected_audience: str, expected_issuer: str,
) -> SamlClaims:
    """验签 + 受众/发行方校验 → 断言要素（fail-closed）。"""
    response_xml, assertion_xml, root = parse_saml_response(response_b64)
    if not verifier(response_xml, assertion_xml):
        raise VastaError(
            code="identity.saml_bad_signature",
            message="SAML 断言签名校验失败（注入验签器拒）",
        )
    assertion = root.find(".//saml:Assertion", _NS)
    issuer_el = assertion.find("saml:Issuer", _NS)
    issuer = issuer_el.text.strip() if issuer_el is not None and \
        issuer_el.text else ""
    if issuer != expected_issuer:
        raise VastaError(
            code="identity.saml_issuer_mismatch",
            message=f"SAML issuer {issuer!r} ≠ 预期 {expected_issuer!r}",
        )
    conditions = assertion.find("saml:Conditions", _NS)
    audience = ""
    if conditions is not None:
        aud_el = conditions.find(".//saml:Audience", _NS)
        audience = aud_el.text.strip() if aud_el is not None and \
            aud_el.text else ""
    if audience != expected_audience:
        raise VastaError(
            code="identity.saml_audience_mismatch",
            message=f"SAML audience {audience!r} ≠ 预期 "
                    f"{expected_audience!r}",
        )
    subject = assertion.find(".//saml:Subject/saml:NameID", _NS)
    name_id = subject.text.strip() if subject is not None and \
        subject.text else ""
    if not name_id:
        raise VastaError(
            code="identity.saml_no_subject",
            message="SAML 断言缺 Subject/NameID",
        )
    attributes: dict[str, str] = {}
    for attr in assertion.findall(
            ".//saml:AttributeStatement/saml:Attribute", _NS):
        name = attr.get("Name", "")
        value_el = attr.find("saml:AttributeValue", _NS)
        if name and value_el is not None and value_el.text:
            attributes[name] = value_el.text.strip()
    return SamlClaims(issuer=issuer, audience=audience, name_id=name_id,
                      attributes=attributes)


__all__ = ["SamlClaims", "SamlVerifier", "parse_saml_response",
           "verify_saml_response"]
