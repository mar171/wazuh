/* Copyright (C) 2015-2022, Wazuh Inc.
 * All rights reserved.
 *
 * This program is free software; you can redistribute it
 * and/or modify it under the terms of the GNU General Public
 * License (version 2) as published by the FSF - Free Software
 * Foundation.
 */

#include <gtest/gtest.h>
#include "testUtils.hpp"
#include <vector>

#include "opBuilderHelperFilter.hpp"
#include "base/baseTypes.hpp"

using namespace builder::internals::builders;
using namespace base;

using FakeTrFn = std::function<void(std::string)>;
static FakeTrFn tr = [](std::string msg){};

auto createEvent = [](const char * json){
    return std::make_shared<EventHandler>(std::make_shared<json::Document>(json));
};

// Build ok
TEST(opBuilderHelperStringLT, Builds)
{
    Document doc{R"({
        "check":
            {"field2check": "+s_lt/abcd"}
    })"};
    ASSERT_NO_THROW(opBuilderHelperStringLT(doc.get("/check"), tr));
}

// Build incorrect number of arguments
TEST(opBuilderHelperStringLT, Builds_incorrect_number_of_arguments)
{
    Document doc{R"({
        "check":
            {"field2check": "+s_lt/test_value/test_value2"}
    })"};
    ASSERT_THROW(opBuilderHelperStringLT(doc.get("/check"), tr), std::runtime_error);
}

// Test ok: static values
TEST(opBuilderHelperStringLT, Static_string_ok)
{
    Document doc{R"({
        "check":
            {"field2check": "+s_lt/ABCD"}
    })"};

    Observable input = observable<>::create<Event>(
        [=](auto s)
        {
            // less
            s.on_next(createEvent(R"(
                {"field2check":"ABC"}
            )"));
            // Equal
            s.on_next(createEvent(R"(
                {"field2check":"ABCD"}
            )"));
            // Greater
            s.on_next(createEvent(R"(
                {"field2check":"ABCDE"}
            )"));
            // Greater with different case
            s.on_next(createEvent(R"(
                {"field2check":"BBBB"}
            )"));
            // Less with different case
            s.on_next(createEvent(R"(
                {"field2check":"AABCD"}
            )"));
            // lower case are greater
            s.on_next(createEvent(R"(
                {"field2check":"abc"}
            )"));
            s.on_next(createEvent(R"(
                {"field2check":"abcd"}
            )"));
            s.on_next(createEvent(R"(
                {"field2check":"abcde"}
            )"));
            // Other fields will be ignored
            s.on_next(createEvent(R"(
                {"otherfield":"abcd"}
            )"));
            s.on_next(createEvent(R"(
                {"otherfield":"abcd"}
            )"));
            s.on_completed();
        });

    Lifter lift = opBuilderHelperStringLT(doc.get("/check"), tr);
    Observable output = lift(input);
    vector<Event> expected;
    output.subscribe([&](Event e) { expected.push_back(e); });
    ASSERT_EQ(expected.size(), 2);
    ASSERT_STREQ(expected[0]->getEvent()->get("/field2check").GetString(), "ABC");
    ASSERT_STREQ(expected[1]->getEvent()->get("/field2check").GetString(), "AABCD");
}

// Test ok: static values (numbers, compare as string)
TEST(opBuilderHelperStringLT, Static_number_ok)
{
    Document doc{R"({
        "check":
            {"field2check": "+s_lt/50"}
    })"};

    Observable input = observable<>::create<Event>(
        [=](auto s)
        {
            // Less
            s.on_next(createEvent(R"(
                {"field2check":"499"}
            )"));
            // Equal
            s.on_next(createEvent(R"(
                {"field2check":"50"}
            )"));
            // Greater
            s.on_next(createEvent(R"(
                {"otherfield":"51"}
            )"));
            s.on_completed();
        });

    Lifter lift = opBuilderHelperStringLT(doc.get("/check"), tr);
    Observable output = lift(input);
    vector<Event> expected;
    output.subscribe([&](Event e) { expected.push_back(e); });
    ASSERT_EQ(expected.size(), 1);
    ASSERT_STREQ(expected[0]->getEvent()->get("/field2check").GetString(), "499");
}

// Test ok: dynamic values (string)
TEST(opBuilderHelperStringLT, Dynamics_string_ok)
{
    Document doc{R"({
        "check":
            {"field2check": "+s_lt/$ref_key"}
    })"};

    Observable input = observable<>::create<Event>(
        [=](auto s)
        {
            // Less
            s.on_next(createEvent(R"(
                {
                    "field2check":"ABCD",
                    "ref_key":"abcd"
                }
            )"));
            // Equal
            s.on_next(createEvent(R"(
                {
                    "field2check":"ABCD",
                    "ref_key":"ABCD"
                }
            )"));
            // GREATER
            s.on_next(createEvent(R"(
                {
                    "otherfield":"abcd",
                    "ref_key":"ABCD"
                }
            )"));
            s.on_completed();
        });

    Lifter lift = opBuilderHelperStringLT(doc.get("/check"), tr);
    Observable output = lift(input);
    vector<Event> expected;
    output.subscribe([&](Event e) { expected.push_back(e); });
    ASSERT_EQ(expected.size(), 1);
    ASSERT_STREQ(expected[0]->getEvent()->get("/field2check").GetString(), "ABCD");
}