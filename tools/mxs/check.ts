// MAXScript 문법 검사 CLI — HAG87/vscode-maxscript-lsp(MIT)의 ANTLR 문법으로 파싱한다.
// 사용: node mxs_check.cjs < script.ms
//   → {"ok", "errors": [{"line","col","msg"}], "calls": [{"name","line"}], "members": [{"obj","name","line"}]}
// calls = 함수처럼 호출된 이름, members = a.b 형태 접근 (함수 사전 검사용, 선언 이름은 Python 쪽에서 판별)
import { CharStream, CommonTokenStream, BaseErrorListener, ParseTreeWalker, ParserRuleContext } from "antlr4ng";
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
const tree = parser.program();

const calls: { name: string; line: number }[] = [];
const members: { obj: string; name: string; line: number }[] = [];
const ruleName = (c: ParserRuleContext) => parser.ruleNames[c.ruleIndex];
const walker = {
    visitTerminal() {}, visitErrorNode() {}, exitEveryRule() {},
    enterEveryRule(ctx: ParserRuleContext) {
        const rule = ruleName(ctx);
        const line = ctx.start?.line ?? 0;
        if (rule === "postfixExpr" && ctx.children && ctx.children.length >= 2) {
            const head = ctx.children[0] as ParserRuleContext;
            const ops = ctx.children.slice(1) as ParserRuleContext[];
            const headText = head.getText();
            // a.b ...  (첫 접근만: polyop.weldVerts 처럼 구조체.멤버)
            const first = ops[0];
            if (first && ruleName(first) === "postfixOp" && first.getText().startsWith(".")) {
                members.push({ obj: headText, name: first.getText().slice(1), line });
            } else if (first && ruleName(first) === "postfixOp" && !first.getText().startsWith("[")
                       && /^[A-Za-z_][A-Za-z0-9_]*$/.test(headText)) {
                calls.push({ name: headText, line });  // foo arg / foo()
            }
        }
    },
};
ParseTreeWalker.DEFAULT.walk(walker as never, tree);
process.stdout.write(JSON.stringify({ ok: errors.length === 0, errors, calls, members }));
