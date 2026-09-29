# Customer level workflow

@node customer_level field | Customer level | Canonical customer segmentation field.
@node customer_tier field | Customer tier | Legacy name for customer level.
@node pricing_job service | Pricing job | Calculates the offer shown to customers.
@node offer_dashboard dashboard | Offer dashboard | Displays the calculated offer.

@edge level_to_pricing customer_level configures pricing_job confirmed 1.0 | customer_level configures pricing_job
@edge tier_to_pricing customer_tier configures pricing_job confirmed 0.9 | customer_tier configures pricing_job
@edge pricing_to_dashboard pricing_job feeds offer_dashboard inferred 0.7 | pricing_job feeds offer_dashboard
