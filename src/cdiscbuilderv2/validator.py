from typing import Any, Dict, List, Optional, Tuple, Union
import yaml
from .sql_parser import SQLParser


VALID_TYPES = {"str", "int", "float", "date", "datetime", "bool", "string", "integer", "number"}
VALID_VERIFICATION_RULES = {"unique", "not_missing", "range", "valid_values", "compare"}


class YamaaValidationError(Exception):
    """Exception raised when a Yamaa schema violates the specification standard."""
    pass


class YamaaSchemaValidator:
    """
    Validates a Yamaa YAML specification against the CDISC Yamaa schema standard.
    Checks syntax, mandatory fields, expression derivations, SQL filters, and verification rules.
    """

    def __init__(self, spec: Union[str, Dict[str, Any]]):
        self.raw_spec = spec
        self.spec: Optional[Dict[str, Any]] = None
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self._parse()

    def _parse(self) -> None:
        """Parses raw input into dictionary if needed."""
        if isinstance(self.raw_spec, str):
            try:
                parsed = yaml.safe_load(self.raw_spec)
                if not isinstance(parsed, dict):
                    # Handle legacy list-based spec (e.g. DM: [...])
                    if isinstance(parsed, list) and len(parsed) > 0:
                        parsed = parsed[0]
                    else:
                        self.errors.append("Schema root must be a YAML mapping (dictionary).")
                        return
                self.spec = parsed
            except yaml.YAMLError as e:
                self.errors.append(f"YAML Syntax Error: {e}")
                self.spec = None
        elif isinstance(self.raw_spec, dict):
            self.spec = self.raw_spec
        else:
            self.errors.append("Invalid specification type. Expected YAML string or dict.")
            self.spec = None

    def validate(self) -> Tuple[bool, List[str], List[str]]:
        """
        Executes full validation suite on the schema.
        Returns (is_valid, errors, warnings).
        """
        if self.errors or self.spec is None:
            return False, self.errors, self.warnings

        self._validate_root_fields()
        self._validate_keys()
        self._validate_columns()
        self._validate_rows()
        self._validate_verifications()

        is_valid = len(self.errors) == 0
        return is_valid, self.errors, self.warnings

    def _validate_root_fields(self) -> None:
        """Checks for required root fields in Yamaa spec."""
        if not self.spec:
            return

        # Check domain
        if "domain" not in self.spec:
            self.errors.append("Missing required root field: 'domain'")
        elif not isinstance(self.spec["domain"], str) or not self.spec["domain"].strip():
            self.errors.append("Field 'domain' must be a non-empty string.")

        # Check datasets
        if "datasets" not in self.spec:
            self.warnings.append("Root field 'datasets' is omitted (defaults to ODM).")
        elif not isinstance(self.spec["datasets"], dict):
            self.errors.append("Field 'datasets' must be a mapping of {DatasetName: Path}.")

        # Check keys
        if "keys" not in self.spec:
            self.errors.append("Missing required root field: 'keys'")
        elif not isinstance(self.spec["keys"], list) or len(self.spec["keys"]) == 0:
            self.errors.append("Field 'keys' must be a non-empty list of key column names.")

        # Check columns
        if "columns" not in self.spec:
            self.errors.append("Missing required root field: 'columns'")
        elif not isinstance(self.spec["columns"], list):
            self.errors.append("Field 'columns' must be a list of column definitions.")

    def _validate_keys(self) -> None:
        """Validates key columns."""
        if not self.spec or "keys" not in self.spec or not isinstance(self.spec["keys"], list):
            return

        keys = self.spec["keys"]
        for k in keys:
            if not isinstance(k, str) or not k.strip():
                self.errors.append(f"Invalid key column name in 'keys': {k}")

        if "STUDYID" not in keys:
            self.warnings.append("Best practice: CDISC SDTM domains should include 'STUDYID' in 'keys'.")
        if "USUBJID" not in keys and self.spec.get("domain") != "_DM_REF":
            self.warnings.append("Best practice: CDISC SDTM domains should include 'USUBJID' in 'keys'.")

    def _validate_columns(self) -> None:
        """Validates column definitions and derivations."""
        if not self.spec or "columns" not in self.spec or not isinstance(self.spec["columns"], list):
            return

        defined_cols = set()
        for idx, col in enumerate(self.spec["columns"]):
            if not isinstance(col, dict):
                self.errors.append(f"Column definition at index {idx} must be a dictionary.")
                continue

            col_name = col.get("name")
            if not col_name or not isinstance(col_name, str):
                self.errors.append(f"Column at index {idx} is missing a valid 'name'.")
                continue

            if col_name in defined_cols:
                self.errors.append(f"Duplicate column name defined in 'columns': '{col_name}'.")
            defined_cols.add(col_name)

            # Type check
            col_type = col.get("type")
            if col_type and str(col_type).lower() not in VALID_TYPES:
                self.warnings.append(f"Column '{col_name}' has non-standard type: '{col_type}'. Standard: {list(VALID_TYPES)}")

            # Derivation check
            if "derivation" in col:
                self._validate_derivation(col_name, col["derivation"])

        # Check that all keys are defined in columns or derivable
        if "keys" in self.spec and isinstance(self.spec["keys"], list):
            for k in self.spec["keys"]:
                if k not in defined_cols:
                    self.warnings.append(f"Key column '{k}' is listed in 'keys' but not explicitly defined in 'columns'.")

    def _validate_derivation(self, col_name: str, deriv: Any) -> None:
        """Validates a derivation structure."""
        if not isinstance(deriv, dict):
            self.errors.append(f"Derivation for column '{col_name}' must be a dictionary.")
            return

        recognized = False

        if "source" in deriv:
            recognized = True
            if not isinstance(deriv["source"], str):
                self.errors.append(f"Column '{col_name}' 'source' derivation must be a string identifier.")

        if "literal" in deriv:
            recognized = True

        if "mapping" in deriv:
            recognized = True
            m = deriv["mapping"]
            if not isinstance(m, dict):
                self.errors.append(f"Column '{col_name}' 'mapping' must be a dictionary.")
            elif "dict" not in m and "source" not in m:
                self.errors.append(f"Column '{col_name}' 'mapping' must contain 'source' and 'dict'.")

        if "mapping_from" in deriv:
            recognized = True
            mf = deriv["mapping_from"]
            if not isinstance(mf, dict) or "dataset" not in mf or "key" not in mf or "value" not in mf:
                self.errors.append(f"Column '{col_name}' 'mapping_from' requires 'dataset', 'key', and 'value'.")

        if "row_number" in deriv:
            recognized = True
            rn = deriv["row_number"]
            if not isinstance(rn, dict):
                self.errors.append(f"Column '{col_name}' 'row_number' derivation must be a dictionary.")
            elif "group_by" not in rn:
                self.warnings.append(f"Column '{col_name}' 'row_number' does not specify 'group_by' (will sequence entire dataset).")

        if "function_" in deriv:
            recognized = True
            if not isinstance(deriv["function_"], str):
                self.errors.append(f"Column '{col_name}' 'function_' must be a string function name.")

        if "case" in deriv:
            recognized = True
            if not isinstance(deriv["case"], list):
                self.errors.append(f"Column '{col_name}' 'case' expression must be a list of condition branches.")

        if "sql" in deriv or "expression" in deriv or "value" in deriv:
            recognized = True

        if not recognized:
            self.warnings.append(f"Column '{col_name}' has custom derivation grammar: {list(deriv.keys())}")

    def _validate_rows(self) -> None:
        """Validates row-level slicing specifications."""
        if not self.spec or "rows" not in self.spec:
            return

        rows = self.spec["rows"]
        if not isinstance(rows, list):
            self.errors.append("Field 'rows' must be a list of row slice specifications.")
            return

        row_ids = set()
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                self.errors.append(f"Row slice at index {idx} must be a dictionary.")
                continue

            r_id = row.get("id")
            if not r_id or not isinstance(r_id, str):
                self.errors.append(f"Row slice at index {idx} is missing a valid 'id'.")
            elif r_id in row_ids:
                self.warnings.append(f"Duplicate row slice id: '{r_id}'.")
            else:
                row_ids.add(r_id)

            # Validate SQL Filter
            if "filter" in row:
                sql_filter = str(row["filter"])
                try:
                    SQLParser.parse_to_expr(sql_filter)
                except Exception as e:
                    self.errors.append(f"Row slice '{r_id}' contains invalid SQL filter '{sql_filter}': {e}")

            # Validate row-level derivations
            if "derivations" in row:
                if not isinstance(row["derivations"], dict):
                    self.errors.append(f"Row slice '{r_id}' 'derivations' must be a dictionary of {{ColumnName: Derivation}}.")
                else:
                    for col_name, d_val in row["derivations"].items():
                        self._validate_derivation(f"{r_id}.{col_name}", d_val)

    def _validate_verifications(self) -> None:
        """Validates verification rules."""
        if not self.spec or "verifications" not in self.spec:
            return

        verifs = self.spec["verifications"]
        if not isinstance(verifs, list):
            self.errors.append("Field 'verifications' must be a list of verification rules.")
            return

        for idx, v_rule in enumerate(verifs):
            if not isinstance(v_rule, dict):
                self.errors.append(f"Verification rule at index {idx} must be a dictionary.")
                continue

            for rule_type, rule_cfg in v_rule.items():
                if rule_type not in VALID_VERIFICATION_RULES:
                    self.warnings.append(f"Non-standard verification rule type: '{rule_type}'. Standard rules: {list(VALID_VERIFICATION_RULES)}")

                if isinstance(rule_cfg, dict) and "columns" in rule_cfg:
                    cols = rule_cfg["columns"]
                    if not isinstance(cols, list) or len(cols) == 0:
                        self.errors.append(f"Verification rule '{rule_type}' 'columns' must be a non-empty list.")
