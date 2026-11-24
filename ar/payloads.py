"""What an approval carries, per action. Built by the tool that holds the write, read back to carry it out."""

from pydantic import BaseModel, ConfigDict

from ar.data_model import Channel, Money


class _Payload(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')


class MessageDraft(_Payload):
    """send_message held under P5."""

    contact_id: str
    channel: Channel
    invoice_ids: tuple[str, ...]
    amount: Money
    body: str


class CreditApproval(_Payload):
    """propose_credit held under P10; the credit row exists with status proposed."""

    credit_id: str
    dispute_id: str
    invoice_id: str
    amount: Money


class PaymentApproval(_Payload):
    """apply_payment held under P8 (the reviewer picks one of the candidates) or P15 (no candidate matches)."""

    payment_id: str
    amount: Money
    candidate_invoice_ids: tuple[str, ...]
