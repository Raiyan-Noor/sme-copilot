"""SandboxPay: a simulated payment provider, run as its own local service (its own process, port, API and database).

The app talks to it over HTTP the way it would talk to a real bank or mobile-money API. It never moves real money.
It deliberately imports nothing from `app`: its limits hold even if the app (and its gateway) were compromised.
"""
