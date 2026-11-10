"""Template for BRC's four-manager workflows."""

from abc import ABC, abstractmethod


class BaseBRCWorkflow(ABC):
    """Run one BRC job through IO, AI, Logic, then Data responsibilities."""

    name = ""

    def run(self, ai, logic, data, report, output=None):
        self.announce(data, logic, report)
        report("AI Manager: normalizing restaurant information...")
        proposals = self.ask_ai(ai)
        report("Logic Manager: validating AI output against MUIS evidence...")
        result = self.apply_rules(logic, proposals)
        report("Data Manager: saving the validated result...")
        return self.save(data, result, report, output)

    @abstractmethod
    def announce(self, data, logic, report):
        """Prepare the workflow and report accepted input."""

    @abstractmethod
    def ask_ai(self, ai):
        """Obtain structured proposals from the AI Manager."""

    @abstractmethod
    def apply_rules(self, logic, proposals):
        """Apply deterministic Logic Manager rules to proposals."""

    @abstractmethod
    def save(self, data, result, report, output):
        """Persist validated output through the Data Manager."""
