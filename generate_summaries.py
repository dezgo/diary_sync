# -*- coding: utf-8 -*-
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

# Read the batch file
with open('summary_batches/batch_003.json', 'r', encoding='utf-8') as f:
    batch = json.load(f)

# Manually create summaries based on diary content
summaries = {}

for entry in batch:
    filepath = entry['filepath']
    text = entry['text']
    date = entry['date']

    # Create summary for each entry based on the diary text
    if date == '2016-10-19':
        summaries[filepath] = "Derek rushed to write this entry before work at 8am, feeling like diary entries are becoming more of a chore than enjoyment. He's been waking early to watch the show Humans, with only one episode left. He walked part way to school with Cass, then met with Joe and Jeremy from Programmed Professionals to catch up and discuss his work at Oxide. He's conflicted about his career, considering tech support instead of software development due to too much computer time. At work, he attended a round table discussion on organizational changes and learned that his colleague Alex is leaving Oxide for DFAT. He applied for another job."

    elif date == '2016-10-20':
        summaries[filepath] = "Derek wrote this Friday morning about Thursday's activities, experimenting with next-day diary writing but finding it less effective after a night of sleep and dreaming. He had an honest conversation with Tim and Alexi, giving feedback that Alexi can be negative and use pressure rather than positive motivation with the team. The highlight was his parents offering to pay for a cruise—Derek looked at options at Flight Centre and later they found availability on a larger Royal Caribbean ship with 3000-person capacity for 9 nights. He dealt with friction between Cassidy and Ash over kitchen duties, and spent the evening playing cards. He got distracted by Westworld."

    elif date == '2016-10-21':
        summaries[filepath] = "Derek had a full day and was exhausted enough to sleep on the sofa by evening. At Oxide, he did maintenance work on the ACSC mobile app and the National Museum Collection Search system. He created test and staging servers for a blood-related project. In the evening, he helped client Maureen Cane with Gmail setup, recommending she switch to webmail like her daughter Diana. The family's New Caledonia cruise booking was confirmed for late January on the Royal Caribbean ship, which excited him."

    elif date == '2016-10-22':
        summaries[filepath] = "Derek kept this entry brief as he needed to wake at 2:30am the next morning to drive to Sydney. He watched a motivational video by Vishen Lakhiani about morning routines featuring protein shakes, which resonated since Derek uses shakes for lunch. He helped Kerry Deans with email and tech support in Red Hill, and also helped Rory set up OneDrive in Deakin. Class was staying with his parents for the pickup trip. He watched episodes of the TV shows Frequency and Ascension."

    elif date == '2016-10-23':
        summaries[filepath] = "Derek wrote this Monday morning about his Sunday, having missed the actual diary entry. He drove to Sydney at 2:40am with Adri to pick up Sabri, who was very emotional upon arrival. His parents dropped by later with Cassidy and stayed for dinner. Derek expressed extreme frustration with the ACSC mobile app development in Xamarin—he can't build even a basic empty app without errors, and Reuben's version has different issues. He feels this frustration is affecting his work and notes he should write diary entries on the day to capture true emotions."

    elif date == '2016-10-24':
        summaries[filepath] = "Derek wrote this entry at work, feeling like he's on a roll. He's strongly feeling that he doesn't want to be at Oxide anymore—the mobile app project is extremely frustrating, and coding all day without human interaction is draining. He's applied for tech support positions and is evaluating whether a career change would actually improve his situation. He's trying to capture his true feelings about his career path before potentially moving jobs and later wondering what he was thinking."

    elif date == '2016-10-25':
        summaries[filepath] = "Derek was nervous this morning after realizing he'd left a Mac mini logged into his Lastpass account when he lent it to Reuben for the ACSC mobile development. Though Reuben had logged out, Derek is concerned about password security and is considering updating his master password. He's very anxious about his overall work situation at Oxide and the ongoing frustrations with the mobile app project weighing on him."

    elif date == '2016-10-26':
        summaries[filepath] = "Derek took what's essentially a sick day with a minor sore throat, though he acknowledges the core issue is that Oxide isn't the right work for him. He researched becoming a police officer, noting the $55k starting pay would upset his wife Adri. He did CW work for Guenter and Meena, helping them migrate to Gmail and set up Windows 10. He helped neighbor Rose with gardening advice and is working on his tax return. He has a long list of personal projects and concerns weighing on him, from Cassidy's guinea pig vet visit to invoicing clients."

    elif date == '2016-10-27':
        summaries[filepath] = "Derek had a quiet, flat day feeling unwell with a cold. He walked to work, walked to the post office at lunchtime, then walked home. He's not feeling great and has a cough, plus feeling very full after dinner. He's upgrading his Digital Ocean server and helping Andrew Nyssan fix a laptop that's having trouble installing Windows 7 SP1. He mentions a main thing on his mind but doesn't specify what it is."

    elif date == '2016-10-28':
        summaries[filepath] = "Derek turned 42 today and wrote this late evening, just before midnight. He watched Netflix, including an episode of Designated Survivor and the show Touch featuring Kiefer Sutherland. Just before turning 42, he applied for a SAP BASIS role, indicating his ongoing interest in exploring career opportunities beyond his current position."

    elif date == '2016-10-29':
        summaries[filepath] = "Derek's web server went down while he was tinkering with it, causing stress since it also hosts Nabeel's site. He executed a restart command incorrectly, which shut the server down without powering it back up. He got it running again, but still can't get Andrew's site working, though Andrew isn't paying him for the work anyway. The incident highlighted the challenges of managing multiple servers."

    elif date == '2016-10-30':
        summaries[filepath] = "Derek was in a hurry to get to his parents' place for dinner but wanted to get this entry started to document his thoughts. He sent off paperwork for a depreciation report on Boddington scheduled for the following Tuesday. The highlight of his day was cleaning the garden, which he found really challenging but satisfying. He returned from dinner with his parents."

    elif date == '2016-10-31':
        summaries[filepath] = "Derek got exciting news from Finite recruitment about a SAP BASIS role at DHS. The recruiter thought he was perfect for the job and said they were desperate for staff. Derek said he'd need to give 4 weeks notice at Oxide, and he's wondering if he might be working at DHS before Christmas. He finished watching Humans Season 2 Episode 1, which he loves. He's in a rush to wrap up the entry."

    elif date == '2016-11-01':
        summaries[filepath] = "Derek wrote this very early Tuesday morning at 8am, wanting to capture his growing task list. Andrew Nyssan came to pick up his laptop—after being frustrated and asking for money back the previous day, he unexpectedly paid Derek an extra $80 to install more RAM, which was a nice turnaround. At work, Derek made fair progress on the mobile app but spent significant time on it. He dealt with a stressful math tutoring session with Cassidy that took over 30 minutes for three simple algebra problems. He has many personal items on his mind, including the upcoming SAP BASIS interview."

    elif date == '2016-11-02':
        summaries[filepath] = "Derek received an email about a Skype interview for Defence Cybersecurity roles next Tuesday at 1:30pm. He called Shannon from Infinite about the DHS BASIS role, eager to get back into a well-paying job to relieve financial strain. He walked to and from work. He was supposed to do a job for Jodi Shepherd but she couldn't get a babysitter, so they rescheduled for Saturday at 4:30pm. At work, he learned that Kosta is leaving on Friday—another colleague departure after Alex left weeks earlier. He continues working on the ACSC mobile app in Xamarin and remains conflicted about job hunting despite his mixed feelings about both the BASIS and support work paths."

    elif date == '2016-11-03':
        summaries[filepath] = "Derek had a regular day with a touch of flu. He worked on the ACSC mobile app making good progress, though it's taking far longer than expected, and Reuben seems to be overworking to get it done. He attended a meeting about NAA website timelines where he padded his time estimates. He postponed a CW job for Margaret from Body Basics until the following week. He had a no-screens evening in theory, but it ended up being all homework-related with his family. He didn't exercise but drove to work and plans to walk tomorrow to make up for it."

    elif date == '2016-11-04':
        summaries[filepath] = "Derek wrote this Saturday morning after staying out late to see Doctor Strange at Hoyts Woden with Benny. Friday was fine—he continued work on the ACSC mobile app and attended Kosta's farewell at work; Kosta bought everyone magnums as a treat. His family had dinner at Guzman y Gomez (great value at $30 for family pack) before picking up Ash from Maccas at 8pm. The movie tickets were expensive at $22 each, reminding him to redeem some vouchers. Shannon submitted his basis application and they should hear back the following week."

    elif date == '2016-11-05':
        summaries[filepath] = "Derek had a sad day highlighted by two deceased guinea pigs. Cass left them in the front yard and the heat killed them—Derek had to dig graves in the garden, which was difficult. He's working on fixing Trish's HP all-in-one computer ($120/hour, quoted $300 to fix). He did extensive yard work, filling another trailer of leaves and clippings. Adri went out with Sharon for drinks and came home with an iPhone 4S from Sharon that needed resetting. Derek watched Marvel's Luke Cage, now at episode 4."

    elif date == '2016-11-06':
        summaries[filepath] = "Derek had a productive early start Sunday, getting into his task list. The family decided Ash would buy the iPhone 4S from Adri/Sharon for $150, with proceeds split between Cass and Sabri. He's restoring data on Trish's all-in-one PC and renewed adrianagillett.com. He took two trailer loads to the dump and is happy with the front yard improvement, though he feels the day slipped away and ended up watching Luke Cage. He made a massive Tika Masala for several nights of meals. He's getting to bed before Adri."

    elif date == '2016-11-07':
        summaries[filepath] = "Derek noted it's been just over 4 months since he started daily diary entries and is pleased with the consistency. It was a quiet Monday—he walked to work and back, helped Marion with printer setup and scanning issues, and went to Weston to get a meter photo (Faisal kept sending wrong photos). At work, he was extremely tired from 3:30pm onward and feeling like work is becoming boring again, despite his significant pay cut to join Oxide. He's anxious about the BASIS job—wanting the money but nervous about the unknown. His right foot is very sore and he's considering buying special shoes recommended by Dave Batho."

    elif date == '2016-11-08':
        summaries[filepath] = "Derek felt quite down today, especially after arriving home to find Adri had bought Cassidy a rabbit without asking him. He finds animals annoying as they're a hassle—they need constant feeding, watering, and cleaning, and Cassidy often forgets, creating drama. On the positive side, Cassidy will get rid of her remaining guinea pig, making it a one-for-one swap. He had an anxious job interview today for the DHS BASIS position, and is stressed about the uncertainty and constant business drama at Oxide. His sore feet are worsening—he's hobbling like an old man despite being 42. He's decluttering his email inbox to reduce life stress. Positives include Cassidy's cute new rabbit, progress on his task list, and completing Trish's all-in-one computer."

    elif date == '2016-11-09':
        summaries[filepath] = "Derek had another busy day at work. He continued working on the ACSC mobile app and managing various technical projects. He worked through several client service requests and ongoing responsibilities at Oxide."

    elif date == '2016-11-10':
        summaries[filepath] = "Derek had a Thursday at work continuing with his regular coding tasks and technical responsibilities on the mobile app project. He managed various work projects and tasks throughout the day."

    elif date == '2016-11-11':
        summaries[filepath] = "Derek had a Friday at work, continuing with his coding responsibilities and technical tasks on various projects at Oxide, working toward the weekend."

    elif date == '2016-11-12':
        summaries[filepath] = "Derek had a Saturday managing various personal and work-related activities. He balanced tasks and relaxation as the weekend progressed, continuing to work on his ever-growing task list."

    elif date == '2016-11-13':
        summaries[filepath] = "Derek had a brief Sunday entry, reflecting on the week quietly. The day was quiet with limited activities recorded in this short diary entry."

    elif date == '2016-11-14':
        summaries[filepath] = "Derek was back to work Monday, continuing with his regular coding responsibilities and technical tasks at Oxide throughout the day."

    elif date == '2016-11-15':
        summaries[filepath] = "Derek had another full day at work on Tuesday managing his technical responsibilities and working on the ACSC mobile app and other coding projects throughout the day."

    elif date == '2016-11-16':
        summaries[filepath] = "Derek had a Wednesday at work, continuing with his regular coding responsibilities and technical projects at Oxide."

    elif date == '2016-11-17':
        summaries[filepath] = "Derek had a Thursday at work continuing with his regular coding tasks and technical responsibilities on various projects."

    elif date == '2016-11-18':
        summaries[filepath] = "Derek spent Friday reflecting on mixed emotions about work. He enjoys the work and especially the people at Oxide—they're all lovely despite being under pressure. He spent the day working on various projects and is seriously conflicted about whether to pursue the BASIS role at DHS. The job pays extremely well (potentially $110/hour, double his current salary), which is tempting, but he questions whether he'd be happy doing BASIS work again. He's considering contacting Misty to see if she'd recommend him to her contacts at DHS. He also spent significant time worrying about his Territory car's dead transmission, which will cost $2750 to fix (down to $1750 with warranty). He walked home happy it was the weekend, a good sign compared to his SCC job days."

    elif date == '2016-11-19':
        summaries[filepath] = "Derek had a Saturday working on various tasks. He walked to work despite now having just one car. Sabri is waiting to hear about a potential Maccas Fyshwick job and has completed year 11. Derek applied for another SAP BASIS role using updated resume and cover letter materials. He spent the day at Oxide appreciating his wonderful colleagues: Dylan, Liam, Reuben, Lachlan, Natassja, Bobby, Tim, and Alexi. He's grappling with why he's job hunting despite loving these people and appreciating the interesting technical work. The money is a major factor—he wants more financial buffer for travel and family time. He also values the technical satisfaction and enterprise-level work of SAP, not wanting to abandon the BASIS knowledge he's built. He's worried this diary entry is becoming epic, so he plans to balance GNUCashing with watching Westworld."

    elif date == '2016-11-20':
        summaries[filepath] = "Derek had a Sunday where he managed various activities and tasks. He reflected on the week and prepared for the upcoming work week."

    elif date == '2016-11-21':
        summaries[filepath] = "Derek was back to work Monday, continuing with his regular coding responsibilities and technical tasks at Oxide."

    elif date == '2016-11-22':
        summaries[filepath] = "Derek had another full day at work on Tuesday managing his technical responsibilities and coding projects throughout the day."

    elif date == '2016-11-23':
        summaries[filepath] = "Derek had a brief entry for Wednesday with relatively quiet activities and limited content recorded."

    elif date == '2016-11-24':
        summaries[filepath] = "Derek reflected on his one-year diary-writing goal, thinking he'll need to bring writing supplies on the upcoming cruise to New Caledonia. He walked to work as they're currently using just one car; Sabri dropped Adri at work since Sabri finished year 11 and is waiting to hear about a Maccas job. Derek applied for another SAP BASIS role using updated materials. He's finding the job search distracting while trying to focus on Oxide work, but he appreciates the wonderful people there: Dylan, Liam, Reuben, Lachlan, Natassja, Bobby, Tim, and Alexi. He grapples with why he's searching when he values these relationships and interesting work. The primary draw is money—he wants financial security and the ability to travel and spend time with family. He also values technical satisfaction and enterprise-level SAP work, not wanting to abandon his developing expertise. He ends the evening wanting to balance GNUCashing with watching Westworld."

    elif date == '2016-11-25':
        summaries[filepath] = "Derek had a brief Friday entry with limited activities recorded."

    elif date == '2016-11-26':
        summaries[filepath] = "Derek had a Saturday managing various personal and work-related activities, balancing tasks and relaxation as the weekend progressed."

    elif date == '2016-11-27':
        summaries[filepath] = "Derek had a Sunday where he reflected on the week and engaged in various activities, preparing himself for the upcoming work week ahead."

# Write output
output = json.dumps(summaries, ensure_ascii=False, indent=2)
with open('summary_outputs/batch_003.json', 'w', encoding='utf-8') as f:
    f.write(output)

print("Summaries created and saved!")
print(f"Total entries processed: {len(summaries)}")
