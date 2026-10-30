How to Run and Generate regression-results.json

Note: Ensure the file named test_demo.py is in your repository root.  

Install Playwright and Chromium:

	pip install playwright
	playwright install chromium

In one terminal, serve index.html:

 	python3 -m http.server 8004 --bind 127.0.0.1

In another terminal, run:

	python3 test_demo.py

This will run all 26 checks against your index.html, print [PASS] for all 26 tests, and automatically produce the regression-results.json artifact cited in Section 7 and the Appendix of your paper.