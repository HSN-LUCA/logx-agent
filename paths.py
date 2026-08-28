"""Central path resolution so files are found regardless of the current directory.

Generated databases and evaluation artifacts live at the project root. Every
module resolves them through here instead of using bare filenames, so commands
work whether run from the root or elsewhere.
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def root_path(*parts):
    """Return an absolute path under the project root."""
    return os.path.join(PROJECT_ROOT, *parts)


# Databases (built by data/erp_database.py and data/pos_database.py).
ERP_DB = root_path("erp.db")
POS_DB = root_path("pos.db")

# Ground-truth files (built by eval/ground_truth.py).
GROUND_TRUTH_ERP = root_path("ground_truth.json")


def db_for(schema_id):
    return ERP_DB if schema_id == "erp" else root_path(f"{schema_id}.db")


def ground_truth_for(schema_id):
    if schema_id == "erp":
        return GROUND_TRUTH_ERP
    return root_path(f"ground_truth_{schema_id}.json")
