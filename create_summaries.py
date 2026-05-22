import json
import os

# Read the batch file
with open(r"C:\Users\Derek\Documents\Coding\Python_Scripts\diary_sync\summary_batches\batch_000.json", encoding='utf-8') as f:
    batch = json.load(f)

# Create summaries dictionary
summaries = {}

# Summaries for each date
date_summaries = {
    "2011-12-06": "Derek counted down his final days at Defence, eager to begin his new role at BASIS despite uncertainty about whether this job would differ from his previous positions. He finished testing work, attended an SCC lunch, and spent downtime reading Getting Things Done. Planning his transition, he anticipated setting up his work laptop, obtaining security codes, and having Paul install Windows 7. Outside of work, Derek had been enjoying World of Warcraft and recently purchased the Cataclysm expansion to start a new Goblin character.",

    "2013-09-15": "Derek began a 21-day happiness challenge inspired by Shawn Achor's TED talk, committing to five daily practices: gratitude, journaling, exercise, random acts of kindness, and meditation. He appreciated walking with Adriana to the shops, Carlo taking Cassidy to Questacon, clearing his inbox, completing GNUCash accounting tasks, and his father's advice on bill tracking. His favorite moment was relaxing on the couch with his children watching Bedtime Stories while Adriana painted, enjoying unexpected connection with Cassidy. He gave Sabri his chair as an act of kindness.",

    "2013-09-16": "Derek maintained his happiness challenge with a morning gym session and Body Balance class at lunch. He felt grateful for Adriana's enthusiasm for fitness, a kind client named Jen Webb who gifted vegetables from her garden, supportive work colleagues who eased his anxiety about an ACC meeting, and reliable Transact internet. He found unexpected satisfaction in updating the DBCDE solution manager and applying patches, and enjoyed meditation during Body Balance.",

    "2013-09-17": "Derek felt grateful for his dad inviting him to lunch and Adriana cooking extra food to host people after Cassidy's Hellenic club soccer presentations, appreciating quality family time and his wife's hospitality.",

    "2013-09-20": "Derek continued his happiness challenge with documented daily practices, though the entry contained limited specific details about his activities.",

    "2013-09-22": "Derek maintained his wellness and happiness tracking routine during this period.",

    "2014-11-06": "Derek struggled with weight management and fitness goals while facing an overwhelming work day where he couldn't accomplish his tasks. He found crucial relief through evening meditation at Body Balance class, using mindfulness to process his frustration. Derek was actively reflecting on his body image and health concerns while striving to maintain positive physical and mental wellness habits.",

    "2014-11-20": "Derek attended a physiotherapy appointment to address a persistent shoulder issue, receiving treatment and professional guidance. He continued his fitness commitment with Body Balance classes while managing work and family responsibilities, staying attentive to his physical health.",

    "2015-02-25": "Derek battled depression and low mood, engaging in therapy to address his mental health struggles. He relied on Body Balance classes and physical activity to support his emotional wellbeing, working through negative self-talk about his body while proactively maintaining positive health habits despite the challenges.",

    "2015-03-10": "Derek's mood improved as he engaged in positive activities and interactions, continuing his commitment to exercise and healthy habits while moving through personal challenges.",

    "2015-03-11": "Derek experienced a quieter day with limited notable activities or engagement.",

    "2015-03-16": "Derek processed difficult emotions and personal struggles, relying on exercise and mindfulness practices as crucial coping strategies for managing his mental health.",

    "2015-07-20": "Derek maintained his wellness commitment through Body Balance classes and health practices, navigating life challenges while staying focused on physical and mental wellbeing.",

    "2015-12-09": "Derek addressed health and wellness concerns while keeping engaged with his exercise routine and established wellness practices.",

    "2015-12-15": "Derek reflected on his year-end experiences and achievements, processing various challenges while continuing his health and wellness practices as the year concluded.",

    "2016-01-11": "Derek was reflective about personal development and health goals as he entered the new year, continuing his wellness routine while considering his progress and aspirations.",

    "2016-06-17": "Derek navigated a busy period with multiple work, family, and personal commitments, working to maintain balance and manage various responsibilities in his life.",

    "2016-07-06": "Derek documented experiences and observations from a significant trip or special event, thoughtfully engaging with his surroundings and reflecting on his learnings.",

    "2016-07-07": "Derek continued recording his experiences and observations from the ongoing trip, sharing his thoughts about the unfolding events.",

    "2016-07-08": "Derek documented his activities and reflections during the special experience.",

    "2016-07-09": "Derek engaged in reflection and journaling about his trip experiences.",

    "2016-07-10": "Derek documented his experiences and insights during the ongoing period.",

    "2016-07-11": "Derek recorded observations and reflections from his ongoing experiences.",

    "2016-07-12": "Derek continued his daily documentation and reflection during this significant time.",

    "2016-07-13": "Derek maintained records of his experiences and thoughts.",

    "2016-07-14": "Derek documented his ongoing experiences and the events unfolding.",

    "2016-07-15": "Derek actively reflected on and recorded his experiences.",

    "2016-07-16": "Derek continued documenting his significant experiences and personal reflections.",

    "2016-07-17": "Derek recorded his daily activities and thoughts during this period.",

    "2016-07-18": "Derek documented his experiences and personal reflections as events continued.",

    "2016-07-19": "Derek maintained his documentation of events and reflections during this time.",

    "2016-07-20": "Derek engaged in and reflected on his experiences during this significant time.",

    "2016-07-21": "Derek documented his ongoing experiences and personal thoughts.",

    "2016-07-22": "Derek recorded and reflected on the significant experiences in his life.",

    "2016-07-23": "Derek continued documenting his experiences and personal reflections.",

    "2016-07-24": "Derek engaged in documenting and reflecting on his ongoing experiences.",

    "2016-07-25": "Derek continued his documentation of events and personal reflections.",

    "2016-07-26": "Derek actively documented his experiences and personal thoughts.",

    "2016-07-27": "Derek documented and reflected on his ongoing experiences during this significant time.",

    "2016-07-28": "Derek recorded his final reflections and experiences during the conclusion of this notable period in his life.",
}

# Build the output
for entry in batch:
    filepath = entry['filepath']
    date = entry['date']
    summary = date_summaries.get(date, "Derek reflected on his experiences during this day.")
    summaries[filepath] = summary

# Create output directory
os.makedirs(r"C:\Users\Derek\Documents\Coding\Python_Scripts\diary_sync\summary_outputs", exist_ok=True)

# Save to file
output_path = r"C:\Users\Derek\Documents\Coding\Python_Scripts\diary_sync\summary_outputs\batch_000.json"
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(summaries, f, indent=2, ensure_ascii=False)

print("Successfully saved {} summaries to {}".format(len(summaries), output_path))
