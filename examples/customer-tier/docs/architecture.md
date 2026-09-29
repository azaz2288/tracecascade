# Customer tier dependencies

The discount job reads customer_tier to choose the discount schedule.
The revenue dashboard consumes discounted order values from the discount job.
The renewal commitment is reviewed against the revenue dashboard every Monday.
The account playbook uses the renewal commitment to select outreach priority.
The revenue dashboard also includes the outreach forecast from the account playbook.
