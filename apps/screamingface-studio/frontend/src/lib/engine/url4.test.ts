import linked from "./__fixtures__/linked.json";
import { linkCandidate, quoteText } from "./url4";

describe("quoteText", () => {
  it("wraps text in single quotes", () => {
    expect(quoteText("hello")).toBe("'hello'");
  });

  it("escapes backslashes before quotes, as url4's _quote does", () => {
    expect(quoteText("it's")).toBe("'it\\'s'");
    expect(quoteText("a \\ b")).toBe("'a \\\\ b'");
    expect(quoteText("\\'")).toBe("'\\\\\\''");
  });
});

describe("linkCandidate", () => {
  // Golden strings from the SDK's own link_candidate (scripts/gen-link-fixtures.py).
  it.each(Object.entries(linked))(
    "matches the SDK byte for byte (%s)",
    (_name, { candidate, benchmark, linked: expected }) => {
      expect(linkCandidate(candidate, benchmark)).toBe(expected);
    },
  );

  it("quotes a prompt containing a quote and a backslash", () => {
    expect(linkCandidate("(a:0.0:/m($input)!'it\\'s \\\\')!'$a'", "B")).toBe(
      "(candidate:0.0:'(a:0.0:/m($input)!\\'it\\\\\\'s \\\\\\\\\\')!\\'$a\\'', B)!''",
    );
  });
});
