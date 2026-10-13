"""Shared teacher-facing reporting helpers for BiteFinder automated tests."""

from pprint import pformat


def show_case(
    case_id,
    function,
    purpose,
    test_input,
    expected,
    actual,
):
    """Print the input, expected output, actual output and result for one test."""

    passed = actual == expected

    print("\n" + "=" * 72)
    print(case_id)
    print("=" * 72)

    print(f"Function: {function}")
    print(f"Purpose: {purpose}")

    print("\nInput:")
    print(
        pformat(
            test_input,
            sort_dicts=False,
        )
    )

    print("\nExpected output:")
    print(
        pformat(
            expected,
            sort_dicts=False,
        )
    )

    print("\nActual output:")
    print(
        pformat(
            actual,
            sort_dicts=False,
        )
    )

    print(
        f"\nResult: "
        f"{'PASS' if passed else 'FAIL'}"
    )

    return passed


def show_summary(
    group_name,
    total_tests,
    failures,
):
    """Print the final summary for one BiteFinder test group."""

    failed_count = len(failures)
    passed_count = total_tests - failed_count

    print("\n" + "=" * 72)
    print(f"{group_name.upper()} TEST SUMMARY")
    print("=" * 72)

    print(
        f"Tests run: {total_tests}"
    )

    print(
        f"Passed: {passed_count}"
    )

    print(
        f"Failed: {failed_count}"
    )

    if failures:
        print("\nFailed tests:")

        for test_name, error in failures:
            print(
                f"- {test_name}: "
                f"{type(error).__name__}: {error}"
            )


def show_group_start(
    group_name,
    description,
):
    """Print a heading before a group of tests starts."""

    print("\n" + "#" * 72)
    print(f"BITEFINDER - {group_name.upper()}")
    print("#" * 72)

    print(description)