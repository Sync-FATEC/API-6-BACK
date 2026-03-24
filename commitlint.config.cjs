module.exports = {
  extends: ["@commitlint/config-conventional"],

  plugins: [
    {
      rules: {
        "ticket-rule": (parsed) => {
          const { subject } = parsed;

          if (!subject) return [true];

          const hasTicket = /^#SCRUM-\d+ /.test(subject);

          return [
            hasTicket,
            "ERRO: A mensagem deve começar com o ticket! Exemplo: feat: #SCRUM-123 minha descrição",
          ];
        },
      },
    },
  ],

  rules: {
    "subject-case": [0],
    "ticket-rule": [2, "always"],
  },
};
