# -*- coding: utf-8 -*-
from typing import Iterable, Set, Optional, List, Any, TextIO
import csv
import sys
import datetime
import logging
from decimal import Decimal

from ofxstatement.plugin import Plugin as BasePlugin
from ofxstatement.parser import CsvStatementParser
from ofxstatement.exceptions import ParseError
from ofxstatement.plugins.nl.statement import Statement, StatementLine

assert sys.version_info[0] >= 3, "At least Python 3 is required."

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class Parser(CsvStatementParser):

    date_format = "%d-%m-%Y"

    mappings = {
        'date': 0,
        'memo': 5,
        'amount': 8,
    }

    unique_id_set: Set[str]

    def __init__(self, fin: TextIO, account_id: str,
                 currency: str | None = None) -> None:
        super().__init__(fin)
        self.currency = currency
        self.statement = Statement(bank_id="STDGNL21",
                                   account_id=account_id,
                                   currency=currency or "EUR",
                                   account_type="CHECKING")
        self.unique_id_set = set()
        self.header = [["Data",
                        "Hora",
                        "Data Valor",
                        "Produto",
                        "ISIN",
                        "Descrição",
                        "T.",
                        "Mudança",
                        "",
                        "Saldo",
                        "",
                        "ID da Ordem"]]

    def parse(self) -> Statement:
        stmt: Statement = super().parse()

        try:
            assert len(self.header) == 0, \
                "Header not completely read: {}".format(str(self.header))
        except Exception as e:
            raise ParseError(0, str(e))

        stmt.start_balance = stmt.end_balance = None
        if stmt.lines:
            stmt.start_date = min(sl.date for sl in stmt.lines)
            stmt.end_date = max(sl.date for sl in stmt.lines)
            stmt.end_date += datetime.timedelta(days=1)

        logger.debug('stmt: %r', stmt)

        return stmt

    def split_records(self) -> Iterable[Any]:
        return csv.reader(self.fin, delimiter=',')

    def parse_record(self, line: List[str]) -> Optional[StatementLine]:
        logger.debug('header count: %d; line #%d: %s',
                     len(self.header),
                     self.cur_record,
                     line)

        if len(self.header) >= 1:
            hdr = self.header.pop(0)
            logger.debug('header: %s', hdr)
            assert line == hdr, \
                "Expected: {}\ngot: {}".format(hdr, line)
            return None

        stmt_line: StatementLine = super().parse_record(line)

        if stmt_line.amount is None or stmt_line.amount == 0:
            return None

        line_currency = line[self.mappings['amount'] - 1]
        if self.currency is not None and line_currency != self.currency:
            return None

        if stmt_line.memo in ['Dividendo', 'Imposto sobre dividendo']:
            stmt_line.trntype = "DIV"
        elif stmt_line.memo == 'Juros':
            stmt_line.trntype = "INT"
        elif stmt_line.memo == 'Crédito de divisa':
            stmt_line.trntype = "DEP"
        elif stmt_line.memo == 'Levantamento de divisa':
            stmt_line.trntype = "XFER"
        elif stmt_line.amount < 0:
            stmt_line.trntype = "DEBIT"
        else:
            stmt_line.trntype = "CREDIT"

        stmt_line.__class__ = StatementLine
        stmt_line.adjust(self.unique_id_set)

        if line[self.mappings['memo'] - 2]:
            stmt_line.memo += ' ' + line[self.mappings['memo'] - 2]
            if line[self.mappings['memo'] - 1]:
                stmt_line.memo +=\
                    ' (' + line[self.mappings['memo'] - 1] + ')'

        return stmt_line

    def parse_decimal(self, value: str) -> Decimal:
        return super().parse_decimal(value) if value else Decimal(0)


class Plugin(BasePlugin):
    """DEGIRO trader platform, Portugal, CSV"""
    def get_parser(self, f: str) -> Parser:
        fin = open(f, "r", encoding="UTF-8") if isinstance(f, str) else f
        try:
            account_id = self.settings['account_id']
        except Exception:
            raise RuntimeError("""
Please define an 'account_id' in the ofxstatement configuration.

Run

$ ofxstatement edit-config

for more information.
""")
        currency = self.settings.get('currency', None)
        return Parser(fin, account_id, currency)
