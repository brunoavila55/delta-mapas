class BillingError(Exception):
    pass


class InsufficientCredits(BillingError):
    pass


class ProcessingPriceNotConfigured(BillingError):
    pass


class CreditOperationConflict(BillingError):
    pass


class CreditInvariantError(BillingError):
    pass
