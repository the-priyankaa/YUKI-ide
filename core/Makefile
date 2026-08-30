.PHONY: run test proof clean install uninstall deps deps-fix

run:
	PYTHONPATH=src python3 -m stdedit.main $(FILE) $(ARGS)

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

proof:
	bash scripts/deps-proof.sh

clean:
	find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
	rm -f deps-proof.txt scripts/deps-proof.txt

install:
	PYTHONPATH=src python3 -m stdedit.install install

uninstall:
	PYTHONPATH=src python3 -m stdedit.install uninstall

deps:
	PYTHONPATH=src python3 -m stdedit.install deps

deps-fix:
	PYTHONPATH=src python3 -m stdedit.install deps --fix
