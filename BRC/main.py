"""BRC launch and backward-compatible application entry points."""

from BRC.classes.services.workflows.contracts.base_brc_workflow import BaseBRCWorkflow
from BRC.classes.services.brc_application import BRCApplication
from BRC.classes.services.workflows.build_database_workflow import BuildDatabaseWorkflow
from BRC.classes.services.workflows.check_restaurants_workflow import CheckRestaurantsWorkflow
from BRC.classes.services.cli.command_line import CommandLine


Workflow = BaseBRCWorkflow
run = BRCApplication.run_once
main = CommandLine.main


__all__ = [
    "BRCApplication",
    "BuildDatabaseWorkflow",
    "CheckRestaurantsWorkflow",
    "CommandLine",
    "Workflow",
    "main",
    "run",
]


if __name__ == "__main__":
    raise SystemExit(CommandLine.main())
