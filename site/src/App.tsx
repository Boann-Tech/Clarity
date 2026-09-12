import { useRef } from 'react';
import { motion, useInView } from 'framer-motion';
import './App.css';

/* ─── Framer Motion Variants ─── */
const fadeUp = {
  hidden: { opacity: 0, y: 40 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.6, ease: [0.25, 0.46, 0.45, 0.94] } as const,
  },
} as const;

const stagger = {
  visible: {
    transition: { staggerChildren: 0.1, delayChildren: 0.15 } as const,
  },
} as const;

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: '-80px' });
  return (
    <motion.div
      ref={ref}
      className="section-header"
      initial="hidden"
      animate={inView ? 'visible' : 'hidden'}
      variants={fadeUp}
    >
      <h2>{title}</h2>
      {subtitle && <p>{subtitle}</p>}
    </motion.div>
  );
}

/* ─── Hero ─── */
function Hero() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true });

  return (
    <section className="hero" ref={ref}>
      <div className="hero-grid-bg" />
      <div className="hero-content">
        <motion.div
          className="hero-icon-wrapper"
          initial={{ scale: 0, rotate: -180 }}
          animate={inView ? { scale: 1, rotate: 0 } : {}}
          transition={{ type: 'spring', stiffness: 200, damping: 15, delay: 0.1 }}
        >
          <div className="hero-icon">C</div>
        </motion.div>

        <motion.h1
          className="hero-title"
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.7, delay: 0.25 }}
        >
          <span className="hero-title-gradient">Clarity</span>
        </motion.h1>

        <motion.p
          className="hero-tagline"
          initial={{ opacity: 0, y: 20 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.5, delay: 0.4 }}
        >
          Evidence for what you read.
        </motion.p>

        <motion.p
          className="hero-sub"
          initial={{ opacity: 0, y: 20 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.5, delay: 0.55 }}
        >
          A browser extension that checks factual claims against authoritative sources.
          Fights misinformation by surfacing evidence — not by telling you what to believe.
        </motion.p>

        <motion.div
          className="btn-group"
          initial={{ opacity: 0, y: 20 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.5, delay: 0.7 }}
        >
          <a href="#install" className="btn btn-primary">
            Install Clarity
            <span className="cta-arrow">↓</span>
          </a>
          <a href="https://github.com/boanntech/clarity" className="btn btn-secondary">
            View on GitHub
          </a>
        </motion.div>

        <motion.div
          className="hero-badges"
          initial={{ opacity: 0 }}
          animate={inView ? { opacity: 1 } : {}}
          transition={{ duration: 0.5, delay: 0.85 }}
        >
          <span className="badge">v0.1.0</span>
          <span className="badge">Chrome MV3</span>
          <span className="badge">MIT License</span>
          <span className="badge">FastAPI Backend</span>
        </motion.div>
      </div>

      <motion.div
        className="scroll-indicator"
        initial={{ opacity: 0 }}
        animate={inView ? { opacity: 1 } : {}}
        transition={{ duration: 0.8, delay: 1.2 }}
      >
        <span>Scroll</span>
        <div className="scroll-line" />
      </motion.div>
    </section>
  );
}

/* ─── Problem Section ─── */
function Problem() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: '-80px' });

  return (
    <section className="section" ref={ref} id="problem">
      <div className="container">
        <motion.div
          initial="hidden"
          animate={inView ? 'visible' : 'hidden'}
          variants={stagger}
        >
          <SectionHeader
            title="The problem with information today"
            subtitle="Every day we read articles, watch videos, and scroll social media where people make factual claims. Some are true. Some are misleading. Some are outright false."
          />
        </motion.div>

        <div className="problem-grid">
          <motion.div
            className="problem-text"
            initial={{ opacity: 0, x: -30 }}
            animate={inView ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.6, delay: 0.2 }}
          >
            <h3>You can't fact-check everything yourself</h3>
            <p>
              Misinformation thrives when claims go unchecked and context is stripped away.
              The usual response is to shout "that's false!" — but that doesn't help anyone
              evaluate information critically.
            </p>
            <p>
              <strong>Clarity takes a different approach.</strong> Instead of telling you
              what to believe, it surfaces the evidence so you can decide for yourself.
              No black boxes. No trusted authorities. Just cited sources and transparent assessments.
            </p>
          </motion.div>

          <motion.div
            className="problem-stats"
            initial={{ opacity: 0, x: 30 }}
            animate={inView ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.6, delay: 0.3 }}
          >
            <div className="stat-card">
              <div className="stat-number">5</div>
              <div className="stat-label">Verdict levels</div>
            </div>
            <div className="stat-card">
              <div className="stat-number">3</div>
              <div className="stat-label">Source tiers</div>
            </div>
            <div className="stat-card">
              <div className="stat-number">100%</div>
              <div className="stat-label">Evidence-backed</div>
            </div>
            <div className="stat-card">
              <div className="stat-number">0</div>
              <div className="stat-label">Black boxes</div>
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}

/* ─── How It Works ─── */
function HowItWorks() {
  const steps = [
    {
      num: 1,
      title: 'Open any article or video',
      desc: 'Clarity works on news articles, blog posts, and YouTube videos with captions.',
    },
    {
      num: 2,
      title: 'Open the Clarity side panel',
      desc: 'Click the Clarity icon in your Chrome toolbar — the side panel opens instantly.',
    },
    {
      num: 3,
      title: 'Check claims on this page',
      desc: 'Clarity scans the visible text, detects factual claims, and searches for evidence from authoritative sources.',
    },
    {
      num: 4,
      title: 'Review evidence-backed assessments',
      desc: 'Every verdict comes with linked sources. No citations? Always Unverified.',
    },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: '-60px' });

  return (
    <section className="section section-alt" ref={ref} id="how-it-works">
      <div className="container">
        <motion.div
          initial="hidden"
          animate={inView ? 'visible' : 'hidden'}
          variants={stagger}
        >
          <SectionHeader
            title="How it works"
            subtitle="Four simple steps to check any claim on the web."
          />
        </motion.div>

        <div className="steps-grid">
          {steps.map((step, i) => (
            <motion.div
              key={step.num}
              className="step-card"
              initial={{ opacity: 0, y: 30 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.5, delay: 0.15 + i * 0.12 }}
              whileHover={{ y: -4 }}
            >
              <div className="step-number">{step.num}</div>
              <h3>{step.title}</h3>
              <p>{step.desc}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Verdict System ─── */
function VerdictSystem() {
  const verdicts = [
    { name: 'Supported', cls: 'tag-supported', meaning: 'The available evidence backs this claim.' },
    { name: 'Contradicted', cls: 'tag-contradicted', meaning: 'The available evidence contradicts this claim.' },
    { name: 'Misleading', cls: 'tag-misleading', meaning: 'The claim omits important context. Requires 2+ independent sources.' },
    { name: 'Unverified', cls: 'tag-unverified', meaning: 'No verified evidence could be found. We don\'t know.' },
    { name: 'Not checkable', cls: 'tag-unverified', meaning: 'This is an opinion, prediction, or value statement.' },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: '-60px' });

  return (
    <section className="section" ref={ref} id="verdicts">
      <div className="container">
        <motion.div
          initial="hidden"
          animate={inView ? 'visible' : 'hidden'}
          variants={stagger}
        >
          <SectionHeader
            title="Verdict system"
            subtitle="Five verdicts — none of them claim absolute truth. Every verdict is a statement about the available evidence, not a declaration of fact."
          />
        </motion.div>

        <motion.div
          className="verdict-table-wrapper"
          initial={{ opacity: 0, y: 30 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.5, delay: 0.2 }}
        >
          <table className="verdict-table">
            <thead>
              <tr>
                <th>Verdict</th>
                <th>What it means</th>
              </tr>
            </thead>
            <tbody>
              {verdicts.map((v, i) => (
                <motion.tr
                  key={v.name}
                  initial={{ opacity: 0, x: -10 }}
                  animate={inView ? { opacity: 1, x: 0 } : {}}
                  transition={{ duration: 0.3, delay: 0.25 + i * 0.08 }}
                >
                  <td>
                    <span className={`tag ${v.cls}`}>
                      {v.name === 'Supported' && '✓ '}
                      {v.name === 'Contradicted' && '✗ '}
                      {v.name === 'Misleading' && '⚠ '}
                      {v.name === 'Unverified' && '? '}
                      {v.name === 'Not checkable' && '– '}
                      {v.name}
                    </span>
                  </td>
                  <td>{v.meaning}</td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </motion.div>

        <motion.div
          className="evidence-callout"
          initial={{ opacity: 0, y: 20 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.5, delay: 0.5 }}
        >
          <p>
            <strong>No citations? No verdict.</strong> Clarity will never show Supported,
            Contradicted, or Misleading without at least one valid, cited source. Without
            evidence, the answer is always <strong>Unverified</strong> — and that's honest.
          </p>
        </motion.div>
      </div>
    </section>
  );
}

/* ─── Source Tiers ─── */
function SourceTiers() {
  const tiers = [
    {
      name: 'Primary',
      color: 'var(--accent-green)',
      dot: '#22c55e',
      desc: 'Government statistics, WHO, CDC, legislation, central banks, court filings, peer-reviewed research.',
      sources: ['Govt Stats', 'WHO', 'CDC', 'Legislation', 'Central Banks', 'Peer Review'],
    },
    {
      name: 'Fact Check',
      color: 'var(--accent-blue)',
      dot: '#3b82f6',
      desc: 'Established, transparent fact-checking organizations with published methodologies.',
      sources: ['Reuters', 'AP', 'PolitiFact', 'Snopes', 'FactCheck.org', 'Full Fact'],
    },
    {
      name: 'Secondary News',
      color: 'var(--text-muted)',
      dot: '#64748b',
      desc: 'Major news outlets — used when primary sources are unavailable.',
      sources: ['BBC', 'Guardian', 'NYT'],
    },
    {
      name: 'Excluded',
      color: 'var(--accent-red)',
      dot: '#ef4444',
      desc: 'Unverified blogs, anonymous forum posts, AI-generated content, and social media — never used as evidence.',
      sources: ['Blogs', 'Forums', 'AI Content', 'Social Media'],
    },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: '-60px' });

  return (
    <section className="section section-alt" ref={ref} id="sources">
      <div className="container">
        <motion.div
          initial="hidden"
          animate={inView ? 'visible' : 'hidden'}
          variants={stagger}
        >
          <SectionHeader
            title="Source quality tiers"
            subtitle="Not all sources are equal. Clarity ranks them by authority and independence."
          />
        </motion.div>

        <div className="tier-grid">
          {tiers.map((tier, i) => (
            <motion.div
              key={tier.name}
              className="tier-card"
              initial={{ opacity: 0, y: 25 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ duration: 0.5, delay: 0.15 + i * 0.1 }}
              whileHover={{ y: -3 }}
            >
              <h4>
                <span className="tier-dot" style={{ background: tier.dot }} />
                {tier.name}
              </h4>
              <p>{tier.desc}</p>
              <div className="tier-sources">
                {tier.sources.map((s) => (
                  <span key={s} className="tier-source-tag">{s}</span>
                ))}
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Check Claims Workflow ─── */
function CheckWorkflow() {
  const steps = [
    { num: 1, title: 'Extract text', desc: 'Clarity reads the visible text from the current page.' },
    { num: 2, title: 'Identify claims', desc: 'Detects factual assertions, separating them from opinions and value statements.' },
    { num: 3, title: 'Search sources', desc: 'Queries authoritative sources across Primary, Fact Check, and Secondary tiers.' },
    { num: 4, title: 'Assess evidence', desc: 'Ranks, deduplicates, and calculates a verdict based on what the evidence shows.' },
    { num: 5, title: 'Present citations', desc: 'Shows you every source with clickable citations so you can verify for yourself.' },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: '-60px' });

  return (
    <section className="section" ref={ref} id="workflow">
      <div className="container">
        <motion.div
          initial="hidden"
          animate={inView ? 'visible' : 'hidden'}
          variants={stagger}
        >
          <SectionHeader
            title="How claims are checked"
            subtitle="Every claim goes through the same rigorous pipeline before you see a verdict."
          />
        </motion.div>

        <motion.div
          className="workflow-steps"
          initial="hidden"
          animate={inView ? 'visible' : 'hidden'}
          variants={stagger}
        >
          {steps.map((step, i) => (
            <motion.div
              key={step.num}
              className="workflow-step"
              variants={fadeUp}
              custom={i}
            >
              <div className="workflow-step-icon">{step.num}</div>
              <div className="workflow-step-content">
                <h4>{step.title}</h4>
                <p>{step.desc}</p>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}

/* ─── Install / CTA ─── */
function InstallCta() {
  const phases = [
    { name: 'Phase 1', status: '✅', desc: 'Extension — UI, extraction, verdict protocol' },
    { name: 'Phase 2', status: '✅', desc: 'Backend — FastAPI, evidence retrieval, source tiering' },
    { name: 'Phase 3', status: '🏗️', desc: 'Cross-platform — in progress' },
    { name: 'Phase 4', status: '🏗️', desc: 'Audio transcription, multi-language, breaking-news monitoring' },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: '-60px' });

  return (
    <section className="section section-alt" ref={ref} id="install">
      <div className="container">
        <motion.div
          className="install-content"
          initial="hidden"
          animate={inView ? 'visible' : 'hidden'}
          variants={stagger}
        >
          <SectionHeader
            title="Get started with Clarity"
            subtitle="The full-stack Clarity system is ready. Run the backend, load the extension, and start checking claims."
          />

          <motion.div className="phases" variants={fadeUp}>
            {phases.map((p) => (
              <div key={p.name} className="phase-row">
                <span className="phase-icon">{p.status}</span>
                <span className="phase-name">{p.name}</span>
                <span className="phase-desc">{p.desc}</span>
              </div>
            ))}
          </motion.div>

          <motion.div className="btn-group" variants={fadeUp}>
            <a href="https://github.com/boanntech/clarity" className="btn btn-primary">
              Install from source
            </a>
            <a href="#how-it-works" className="btn btn-secondary">
              How it works
            </a>
          </motion.div>

          <motion.div className="install-command" variants={fadeUp}>
            <span className="comment"># Clone &amp; run the backend</span><br />
            git clone https://github.com/boanntech/clarity<br />
            cd clarity/backend<br />
            <span className="highlight">docker build -t clarity-backend .</span><br />
            <span className="highlight">docker run -p 8080:8080 clarity-backend</span><br /><br />
            <span className="comment"># Load the extension at chrome://extensions</span><br />
            <span className="highlight">→ Load unpacked → select extension/dist/</span>
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}

/* ─── Footer ─── */
function FooterSection() {
  return (
    <footer className="site-footer">
      <div className="container">
        <p>Built by <a href="https://boanntech.com">BoannTech</a> — Dundalk, Co. Louth, Ireland.</p>
        <div className="footer-links">
          <a href="https://github.com/boanntech/clarity">GitHub</a>
          <a href="https://github.com/boanntech/clarity/issues">Report an issue</a>
          <a href="#verdicts">Verdict system</a>
          <a href="#sources">Source tiers</a>
        </div>
        <p style={{ marginTop: '1rem', fontSize: '0.8rem' }}>
          Evidence for what you read. © {new Date().getFullYear()} BoannTech
        </p>
      </div>
    </footer>
  );
}

/* ─── App ─── */
export default function App() {
  return (
    <>
      <Hero />
      <Problem />
      <HowItWorks />
      <CheckWorkflow />
      <VerdictSystem />
      <SourceTiers />
      <InstallCta />
      <FooterSection />
    </>
  );
}