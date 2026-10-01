vi.mock("../runtime", () => ({
  getEngineUrl: async () => "http://engine.test:9",
}));

import { getEngineClient } from ".";

it("builds a client for the Engine the runtime reports", async () => {
  const fetchSpy = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        headers: { "content-type": "application/json" },
      }),
    );

  await (await getEngineClient()).health();

  expect(fetchSpy.mock.calls[0][0]).toBe("http://engine.test:9/healthz");
  fetchSpy.mockRestore();
});
