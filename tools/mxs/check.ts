// MAXScript 문법 검사 CLI — HAG87/vscode-maxscript-lsp(MIT)의 ANTLR 문법으로 파싱만 한다.
// 사용: node mxs_check.cjs < script.ms   →  {"ok": true|false, "errors": [{"line", "col", "msg"}]}
import { CharStream, CommonTokenStream, BaseErrorListener } from "antlr4ng";
import { mxsLexer } from "./parser/mxsLexer.js";
import { mxsParser } from "./parser/mxsParser.js";
import { readFileSync } from "node:fs";

const errors: { line: number; col: number; msg: string }[] = [];
class Collect extends BaseErrorListener {
    override syntaxError(_r: unknown, _s: unknown, line: number, col: number, msg: string): void {
        if (errors.length < 20) errors.push({ line, col, msg });
    }
}
const code = readFileSync(0, "utf8");
const lexer = new mxsLexer(CharStream.fromString(code));
lexer.removeErrorListeners();
lexer.addErrorListener(new Collect());
const parser = new mxsParser(new CommonTokenStream(lexer));
parser.removeErrorListeners();
parser.addErrorListener(new Collect());
parser.program();
process.stdout.write(JSON.stringify({ ok: errors.length === 0, errors }));
