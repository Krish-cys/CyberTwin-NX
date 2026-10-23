.PHONY: install test demo ui whatif lab-gen lab-up lab-down

install:
	pip install -r requirements.txt

test:
	python -m pytest -q

demo:
	python -m cybertwin demo

ui:
	python -m cybertwin ui --open

whatif:
	python -m cybertwin whatif link_failure --arg a=r2 --arg b=r3
	python -m cybertwin whatif compromise --arg host=h2

lab-gen:
	python -m cybertwin gen-lab

lab-up: lab-gen
	sudo containerlab deploy -t lab/cybertwin.clab.yml

lab-down:
	sudo containerlab destroy -t lab/cybertwin.clab.yml --cleanup
